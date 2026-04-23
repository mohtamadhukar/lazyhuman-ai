#!/usr/bin/env python3
"""Convert PDFs to Markdown using PyMuPDF4LLM."""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional


def check_dependencies() -> None:
    """Check if required dependencies are installed."""
    try:
        import pymupdf4llm  # noqa: F401
        import pymupdf  # noqa: F401
    except ImportError as e:
        error_output = {
            "success": False,
            "partial": False,
            "files": [],
            "error": {
                "type": "DependencyError",
                "message": f"Required dependency not installed: {e.name}",
                "hint": "Install with: pip install pymupdf4llm",
            },
            "summary": {"total": 0, "succeeded": 0, "failed": 0},
        }
        print(json.dumps(error_output, indent=2))
        sys.exit(3)


def parse_page_range(pages_str: str, max_pages: int) -> list[int]:
    """Parse page range string (e.g., '1-5,7,10-12') to list of 0-indexed pages."""
    pages = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start))
            end = min(max_pages, int(end))
            pages.extend(range(start - 1, end))  # Convert to 0-indexed
        else:
            page = int(part)
            if 1 <= page <= max_pages:
                pages.append(page - 1)  # Convert to 0-indexed
    return sorted(set(pages))


def find_pdfs(paths: list[str]) -> list[Path]:
    """Find all PDF files from given paths (files or directories)."""
    pdfs = []
    for path_str in paths:
        path = Path(path_str).expanduser().resolve()
        if path.is_file():
            pdfs.append(path)
        elif path.is_dir():
            pdfs.extend(sorted(path.glob("*.pdf")))
    return pdfs


def extract_metadata(doc) -> dict:
    """Extract PDF metadata from an open document."""
    meta = doc.metadata or {}
    return {
        "title": meta.get("title", "") or "",
        "author": meta.get("author", "") or "",
        "pages": len(doc),
        "created": meta.get("creationDate", "") or "",
        "modified": meta.get("modDate", "") or "",
        "encrypted": doc.is_encrypted,
    }


def convert_pdf(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    pages: Optional[str] = None,
    include_images: bool = False,
    metadata_only: bool = False,
    password: Optional[str] = None,
) -> dict:
    """Convert a single PDF to markdown."""
    import pymupdf
    import pymupdf4llm

    result = {
        "input": str(pdf_path),
        "success": False,
        "images_dir": None,
        "image_count": 0,
    }

    # Check file exists
    if not pdf_path.exists():
        result["error"] = {
            "type": "FileNotFound",
            "message": f"File not found: {pdf_path}",
            "hint": "Check the file path and try again",
        }
        return result

    # Check it's a PDF
    if pdf_path.suffix.lower() != ".pdf":
        result["error"] = {
            "type": "NotAPDF",
            "message": f"File is not a PDF: {pdf_path}",
            "hint": "Provide a file with .pdf extension",
        }
        return result

    try:
        # Open PDF
        doc = pymupdf.open(pdf_path)

        # Handle encrypted PDFs
        if doc.is_encrypted:
            if password:
                if not doc.authenticate(password):
                    doc.close()
                    result["error"] = {
                        "type": "WrongPassword",
                        "message": "Incorrect password provided",
                        "hint": "Try again with the correct password",
                    }
                    return result
            else:
                doc.close()
                result["error"] = {
                    "type": "PasswordRequired",
                    "message": "PDF requires password to open",
                    "hint": "Retry with --password argument",
                }
                return result

        # Extract metadata
        result["metadata"] = extract_metadata(doc)

        # Metadata-only mode
        if metadata_only:
            doc.close()
            result["success"] = True
            result["output"] = None
            result["pages"] = 0
            result["duration"] = 0
            return result

        # Parse page range
        page_list = None
        if pages:
            page_list = parse_page_range(pages, len(doc))
            if not page_list:
                doc.close()
                result["error"] = {
                    "type": "ConversionError",
                    "message": f"Invalid page range: {pages}",
                    "hint": f"Valid range is 1-{len(doc)}",
                }
                return result

        doc.close()

        # Set up output paths
        out_dir = output_dir if output_dir else pdf_path.parent
        out_dir = Path(out_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{pdf_path.stem}.md"

        # Set up image directory if needed
        image_path = None
        if include_images:
            image_path = out_dir / f"{pdf_path.stem}_images"
            image_path.mkdir(parents=True, exist_ok=True)

        # Convert to markdown
        start_time = time.time()
        markdown_text = pymupdf4llm.to_markdown(
            doc=str(pdf_path),
            pages=page_list,
            write_images=include_images,
            image_path=str(image_path) if image_path else None,
        )
        duration = time.time() - start_time

        # Check for empty content (scanned PDF)
        if not markdown_text or len(markdown_text.strip()) < 50:
            result["error"] = {
                "type": "NoTextContent",
                "message": "PDF contains no text (likely scanned images)",
                "hint": "Use OCR tool to extract text from images",
            }
            return result

        # Write output
        output_path.write_text(markdown_text, encoding="utf-8")

        # Count images if extracted
        image_count = 0
        if image_path and image_path.exists():
            image_count = len(list(image_path.glob("*")))
            if image_count > 0:
                result["images_dir"] = str(image_path)
                result["image_count"] = image_count

        result["success"] = True
        result["output"] = str(output_path)
        result["pages"] = len(page_list) if page_list else result["metadata"]["pages"]
        result["duration"] = round(duration, 3)

    except PermissionError:
        result["error"] = {
            "type": "PermissionDenied",
            "message": f"Permission denied accessing: {pdf_path}",
            "hint": "Check file permissions and try again",
        }
    except Exception as e:
        error_msg = str(e)
        if "password" in error_msg.lower() or "encrypted" in error_msg.lower():
            result["error"] = {
                "type": "PasswordRequired",
                "message": "PDF requires password to open",
                "hint": "Retry with --password argument",
            }
        elif "corrupt" in error_msg.lower() or "damaged" in error_msg.lower():
            result["error"] = {
                "type": "CorruptedPDF",
                "message": "PDF file appears to be corrupted",
                "hint": "Try re-downloading or obtaining a fresh copy",
            }
        else:
            result["error"] = {
                "type": "ConversionError",
                "message": f"Conversion failed: {error_msg}",
                "hint": "Check if the PDF is valid and try again",
            }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Markdown using PyMuPDF4LLM"
    )
    parser.add_argument("paths", nargs="+", help="PDF file(s) or directory")
    parser.add_argument(
        "-o", "--output-dir", help="Output directory (default: same as input)"
    )
    parser.add_argument("--pages", help="Page range (e.g., '1-5,7,10-12')")
    parser.add_argument(
        "--images", action="store_true", help="Extract and embed images"
    )
    parser.add_argument(
        "--metadata-only", action="store_true", help="Extract metadata only"
    )
    parser.add_argument("--password", help="Password for encrypted PDFs")

    args = parser.parse_args()

    # Check dependencies before processing
    check_dependencies()

    # Find all PDFs
    pdfs = find_pdfs(args.paths)

    if not pdfs:
        error_output = {
            "success": False,
            "partial": False,
            "files": [],
            "error": {
                "type": "FileNotFound",
                "message": "No PDF files found in specified paths",
                "hint": "Check paths and ensure files exist",
            },
            "summary": {"total": 0, "succeeded": 0, "failed": 0},
        }
        print(json.dumps(error_output, indent=2))
        sys.exit(2)

    # Parse output directory
    output_dir = Path(args.output_dir) if args.output_dir else None

    # Process each PDF
    results = []
    total_pages = 0
    total_duration = 0.0

    for pdf in pdfs:
        result = convert_pdf(
            pdf_path=pdf,
            output_dir=output_dir,
            pages=args.pages,
            include_images=args.images,
            metadata_only=args.metadata_only,
            password=args.password,
        )
        results.append(result)
        if result["success"]:
            total_pages += result.get("pages", 0)
            total_duration += result.get("duration", 0)

    # Build summary
    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded

    output = {
        "success": failed == 0,
        "partial": succeeded > 0 and failed > 0,
        "files": results,
        "summary": {
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
        },
    }

    if succeeded > 0 and not args.metadata_only:
        output["summary"]["total_pages"] = total_pages
        output["summary"]["duration"] = round(total_duration, 3)

    print(json.dumps(output, indent=2))

    # Exit codes
    if failed == 0:
        sys.exit(0)
    elif succeeded > 0:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
