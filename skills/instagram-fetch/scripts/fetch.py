#!/usr/bin/env python3
"""Fetch Instagram reel/post caption + transcribe audio with faster-whisper."""

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path


def _detect_ca_bundle() -> str | None:
    for var in ("LAZYHUMAN_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        v = os.environ.get(var)
        if v and Path(v).is_file():
            return v
    default = Path.home() / ".certs" / "combined-ca-bundle.pem"
    if default.is_file():
        return str(default)
    return None


def _install_relaxed_tls() -> str | None:
    """Support corporate MITM proxies (Zscaler etc.) whose intermediate CAs
    mark BasicConstraints as non-critical — rejected by Python 3.12+'s
    default ``VERIFY_X509_STRICT``. When a trust bundle is available, load
    it and drop the strict flag for SSL contexts created via the stdlib
    and urllib3. No-op when no bundle is found.
    """
    bundle = _detect_ca_bundle()
    if not bundle:
        return None

    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    os.environ.setdefault("SSL_CERT_FILE", bundle)

    _orig_default = ssl.create_default_context

    def _patched_default(*args, **kwargs):
        if not any(kwargs.get(k) for k in ("cafile", "capath", "cadata")):
            kwargs["cafile"] = bundle
            kwargs.pop("capath", None)
            kwargs.pop("cadata", None)
        ctx = _orig_default(*args, **kwargs)
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    ssl.create_default_context = _patched_default
    ssl._create_default_https_context = _patched_default

    try:
        import urllib3.util.ssl_ as _u3ssl

        _orig_u3 = _u3ssl.create_urllib3_context

        def _patched_u3(*args, **kwargs):
            ctx = _orig_u3(*args, **kwargs)
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            try:
                ctx.load_verify_locations(cafile=bundle)
            except Exception:
                pass
            return ctx

        _u3ssl.create_urllib3_context = _patched_u3
        for _mod in list(sys.modules.values()):
            if _mod is None:
                continue
            mod_name = getattr(_mod, "__name__", "")
            if not mod_name.startswith("urllib3"):
                continue
            if getattr(_mod, "create_urllib3_context", None) is _orig_u3:
                _mod.create_urllib3_context = _patched_u3
    except ImportError:
        pass

    try:
        import certifi

        certifi.where = lambda: bundle  # type: ignore[assignment]
    except ImportError:
        pass

    return bundle


_install_relaxed_tls()

import yt_dlp  # noqa: E402


SHORTCODE_RE = re.compile(r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")


def parse_url(url: str) -> tuple[str, str]:
    """Return (shortcode, canonical_url) for an Instagram URL.

    Accepts /reel/<code>, /reels/<code>, /p/<code>, /tv/<code>, with or without
    trailing slash and query string.
    """
    m = SHORTCODE_RE.search(url)
    if not m:
        raise ValueError(f"Could not extract Instagram shortcode from: {url}")
    shortcode = m.group(1)
    # Canonical reel URL — yt-dlp accepts /reel/, /p/, /tv/ interchangeably.
    canonical = f"https://www.instagram.com/reel/{shortcode}/"
    return shortcode, canonical


def fetch_metadata_and_video(
    url: str, tmpdir: str, cookies_from_browser: str | None
) -> tuple[dict, str | None, dict]:
    """Download the video and pull metadata in one yt-dlp call.

    Returns (metadata, video_path, raw_info). video_path is None for
    image-only posts (carousel of photos with no audio track).
    """
    outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": outtmpl,
        "format": "bestvideo*+bestaudio/best",
        "noplaylist": True,
        "ignore_no_formats_error": True,
    }
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    description = info.get("description") or ""
    author = info.get("uploader") or info.get("channel")
    first_line = next(
        (line.strip() for line in description.splitlines() if line.strip()), ""
    )
    title = (first_line[:80] if first_line else f"{author or 'instagram'} reel")

    metadata = {
        "title": title,
        "author": author,
        "description": description,
        "duration_seconds": info.get("duration"),
        "views": info.get("view_count"),
        "upload_date": info.get("upload_date"),
        "shortcode": info.get("id"),
        "url": url,
    }

    # Locate the downloaded file. yt-dlp writes the final file path to
    # info["requested_downloads"][0]["filepath"] after merging.
    video_path = None
    requested = info.get("requested_downloads") or []
    if requested:
        video_path = requested[0].get("filepath")
    if not video_path:
        # Fallback: scan tmpdir for a video-ish file.
        for entry in os.listdir(tmpdir):
            full = os.path.join(tmpdir, entry)
            if os.path.isfile(full) and not entry.endswith((".jpg", ".jpeg", ".png", ".webp")):
                video_path = full
                break

    return metadata, video_path, info


def has_audio_track(video_path: str) -> bool:
    """Return True if the file has at least one audio stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                video_path,
            ],
            capture_output=True, text=True, check=False,
        )
        return "audio" in result.stdout
    except FileNotFoundError:
        # If ffprobe is missing, optimistically assume audio exists; ffmpeg
        # will fail later with a clearer message.
        return True


def extract_audio(video_path: str, tmpdir: str) -> str:
    """Extract 16kHz mono PCM audio from the video. Returns audio file path."""
    audio_path = os.path.join(tmpdir, "audio.wav")
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path,
        ],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-5:]
        raise RuntimeError("ffmpeg failed: " + " | ".join(tail))
    return audio_path


def transcribe(audio_path: str, model_name: str, language: str | None) -> list[dict]:
    """Run faster-whisper on the audio file and return segment dicts."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, compute_type="int8")
    segments, _info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,
    )
    out = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        out.append({
            "text": text,
            "start": float(seg.start),
            "duration": float(seg.end - seg.start),
        })
    return out


def process_single(
    url: str,
    output_dir: str | None,
    model: str,
    language: str | None,
    cookies_from_browser: str | None,
) -> dict:
    result = {"metadata": None, "transcript": None, "error": None}

    try:
        shortcode, canonical = parse_url(url)
    except ValueError as e:
        result["error"] = str(e)
        return result

    with tempfile.TemporaryDirectory(prefix="ig-fetch-") as tmpdir:
        try:
            metadata, video_path, _info = fetch_metadata_and_video(
                canonical, tmpdir, cookies_from_browser
            )
            result["metadata"] = metadata
        except Exception as e:
            result["error"] = f"Metadata/download error: {e}"
            return _maybe_write(result, output_dir, shortcode)

        if not video_path or not os.path.isfile(video_path):
            result["transcript"] = []
            result["error"] = "no video track"
            return _maybe_write(result, output_dir, shortcode)

        if not has_audio_track(video_path):
            result["transcript"] = []
            result["error"] = "no audio track"
            return _maybe_write(result, output_dir, shortcode)

        try:
            audio_path = extract_audio(video_path, tmpdir)
            result["transcript"] = transcribe(audio_path, model, language)
        except Exception as e:
            result["transcript"] = []
            result["error"] = f"Transcript error: {e}"

    return _maybe_write(result, output_dir, shortcode)


def _maybe_write(result: dict, output_dir: str | None, shortcode: str) -> dict:
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{shortcode}.json")
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Instagram caption + transcribed audio."
    )
    parser.add_argument("url", help="Instagram reel/post/IGTV URL")
    parser.add_argument(
        "-o", "--output-dir",
        help="Directory to write <shortcode>.json (in addition to stdout)",
    )
    parser.add_argument(
        "-m", "--model", default="small",
        help="faster-whisper model name (tiny|base|small|medium|large-v3). Default: small",
    )
    parser.add_argument(
        "-l", "--language", default=None,
        help="BCP-47 language hint (default: auto-detect)",
    )
    parser.add_argument(
        "--cookies-from-browser", default=None,
        help="Optional: pass-through to yt-dlp (e.g. safari, chrome). For login-required posts.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    # Sanity checks on system deps — fail loud and early.
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            print(
                f"error: `{binary}` not found on PATH. Install with: brew install ffmpeg",
                file=sys.stderr,
            )
            sys.exit(2)

    result = process_single(
        args.url,
        args.output_dir,
        args.model,
        args.language,
        args.cookies_from_browser,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("error") is None else 1)


if __name__ == "__main__":
    main()
