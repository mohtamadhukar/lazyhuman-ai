---
name: pdf-to-markdown
description: Convert PDF documents to Markdown for analysis and text extraction. Use when user shares PDFs, asks about PDF contents, or needs document analysis. Supports batch conversion, page ranges, and image extraction.
---

# PDF to Markdown Conversion

Convert PDF documents to Markdown using PyMuPDF4LLM for fast, reliable text extraction.

## When to Use This Skill

- User uploads or shares a PDF file
- User asks "what's in this PDF", "summarize this document", etc.
- User needs to analyze, search, or extract content from PDFs
- User wants to convert PDFs to editable format
- User provides multiple PDFs to compare or process

## When NOT to Use

- **Scanned PDFs** (image-only): Suggest OCR tools instead. You can detect these
  with `--metadata-only` - if there's no text content, explain the limitation.
- **PDF forms**: Use specialized form extraction tools
- **Table extraction to CSV**: This outputs markdown only
- **Comparing different PDF parsers**: That was the POC, not this skill

## Basic Usage

```bash
python scripts/convert.py document.pdf
```

The script outputs JSON to stdout. Parse it and present results naturally to the user.

## Handling Results

### Success Response

Parse the JSON output:

```json
{
  "success": true,
  "partial": false,
  "files": [{
    "input": "report.pdf",
    "output": "report.md",
    "pages": 45,
    "success": true,
    "metadata": {...}
  }],
  "summary": {
    "total": 1,
    "succeeded": 1,
    "failed": 0
  }
}
```

**Then:**

1. Read the generated `.md` file
2. Respond to the user's query about the PDF content
3. Quote relevant sections as needed

### Error: Password Required

```json
{
  "success": false,
  "partial": false,
  "files": [
    {
      "input": "encrypted.pdf",
      "success": false,
      "error": {
        "type": "PasswordRequired",
        "message": "PDF requires password to open",
        "hint": "Retry with --password argument"
      }
    }
  ],
  "summary": {
    "total": 1,
    "succeeded": 0,
    "failed": 1
  }
}
```

**Action:**

1. Inform user: "This PDF is password-protected."
2. Ask: "Can you provide the password?"
3. Retry with: `python scripts/convert.py file.pdf --password "user_password"`

### Error: Wrong Password

**Action:**
Ask user for the correct password and retry.

### Error: No Text Content

```json
{
  "success": false,
  "partial": false,
  "files": [
    {
      "input": "scanned.pdf",
      "success": false,
      "error": {
        "type": "NoTextContent",
        "message": "PDF contains no text (likely scanned images)",
        "hint": "Use OCR tool to extract text from images"
      }
    }
  ]
}
```

**Action:**
Explain: "This PDF appears to be a scanned document (images only). PyMuPDF4LLM
extracts text from the PDF's text layer, but this file doesn't have one. You
may need OCR (Optical Character Recognition) to extract text from the images."

### Error: Corrupted PDF

**Action:**
Inform user the file appears damaged and suggest re-downloading or obtaining
a fresh copy.

## Advanced Usage

### Large PDFs: Check Metadata First

For large PDFs (especially if user asks about specific sections):

```bash
# Step 1: Get page count without converting
python scripts/convert.py large.pdf --metadata-only

# Step 2: Convert only relevant pages
python scripts/convert.py large.pdf --pages 10-25
```

**Why:** Avoids converting hundreds of pages when user only needs a section.

### Extract Images

```bash
python scripts/convert.py diagram.pdf --images
```

Images are saved to `{basename}_images/` directory. The JSON response includes:

```json
{
  "images_dir": "diagram_images/",
  "image_count": 12
}
```

You can reference these images in your response if relevant.

### Batch Conversion

```bash
python scripts/convert.py file1.pdf file2.pdf file3.pdf
# or
python scripts/convert.py docs/
```

Process all files. The JSON will include results for each:

```json
{
  "success": false,
  "partial": true,
  "files": [
    {"input": "file1.pdf", "success": true, ...},
    {"input": "file2.pdf", "success": false, "error": {...}}
  ]
}
```

If `partial: true`, some succeeded - explain which ones worked and which failed.

### Page Ranges

```bash
python scripts/convert.py doc.pdf --pages 5-10
python scripts/convert.py doc.pdf --pages 1,5,10-15
```

Useful when:

- User asks about specific pages
- Document is very large
- User wants table of contents or specific chapter

### Custom Output Directory

```bash
python scripts/convert.py doc.pdf -o ~/converted/
```

Places the markdown output in the specified directory instead of alongside the source PDF.

## Error Handling Pattern

When you receive the JSON response, check the `success` field first:

**If `success` is `true`:** All files converted successfully. Read the generated
markdown files and respond to the user's query.

**If `success` is `false` but `partial` is `true`:** Some files succeeded, others
failed. Process the successful conversions and explain which files failed and why.

**If both `success` and `partial` are `false`:** All files failed. Examine the
error type in the first file and take appropriate action:

- **PasswordRequired**: Ask user for the password, retry with `python scripts/convert.py file.pdf --password "user_password"`
- **WrongPassword**: Inform user the password was incorrect, ask again
- **NoTextContent**: Explain this is a scanned PDF (images only) and suggest OCR
- **CorruptedPDF**: Tell user the file appears damaged, suggest re-downloading
- **FileNotFound**: Check the path with the user
- **NotAPDF**: File doesn't have .pdf extension
- **PermissionDenied**: Explain file permission issue
- **DependencyError**: Prompt to install pymupdf4llm
- **ConversionError**: Report the specific error message from the response

## Performance Notes

- **Speed**: ~0.04s/page based on testing (50-page PDF in ~2s)
- **Reliability**: 100% success rate in comparison testing
- **Quality**: Best output among tested tools (vs MinerU, OpenDataLoader)

## Tips

- For very large PDFs, use `--metadata-only` first to check page count
- If user mentions specific pages/sections, use `--pages` to save time
- Images extraction adds minimal overhead, use when diagrams/charts present
- Password retry is fast - don't hesitate to ask user if initial conversion fails

## JSON Output Format Reference

All script invocations return JSON with this structure:

```json
{
  "success": boolean,     // true if all files succeeded
  "partial": boolean,     // true if some succeeded, some failed
  "files": [
    {
      "input": "file.pdf",
      "output": "file.md",   // only if success
      "pages": 45,           // only if success
      "duration": 0.8,       // only if success
      "success": boolean,
      "images_dir": "file_images/" or null,
      "image_count": 12,
      "metadata": {          // always present
        "title": "...",
        "author": "...",
        "pages": 45,
        "created": "2024-01-15",
        "encrypted": false
      },
      "error": {             // only if failed
        "type": "ErrorType",
        "message": "Human-readable message",
        "hint": "What to do next"
      }
    }
  ],
  "summary": {
    "total": 1,
    "succeeded": 1,
    "failed": 0,
    "total_pages": 45,       // only if conversions happened
    "duration": 0.8          // only if conversions happened
  }
}
```

**Note:** Password visibility in process list/history is acceptable for v1.
Future improvement: accept password via stdin or environment variable.
