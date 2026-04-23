#!/usr/bin/env python3
"""Fetch YouTube video transcript and metadata. Supports single videos and playlists."""

import argparse
import json
import os
import ssl
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
        # Force our bundle if caller didn't supply any explicit trust source.
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
        # Submodules (notably urllib3.connection) import create_urllib3_context
        # by name at load time, so they keep a direct reference to the original.
        # Patch every already-imported module that has one.
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

    # yt-dlp builds a raw SSLContext and loads certifi.where() into it.
    # Redirect that to our bundle so the corporate CA chain is trusted.
    try:
        import certifi

        certifi.where = lambda: bundle  # type: ignore[assignment]
    except ImportError:
        pass

    return bundle


_install_relaxed_tls()

import yt_dlp  # noqa: E402
from youtube_transcript_api import YouTubeTranscriptApi  # noqa: E402


LANGUAGE_VARIANTS = {
    "en": ["en", "en-US", "en-GB"],
    "es": ["es", "es-MX", "es-ES"],
    "fr": ["fr", "fr-CA", "fr-FR"],
    "pt": ["pt", "pt-BR", "pt-PT"],
    "zh": ["zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW"],
}


def parse_url(url: str) -> tuple[str, str]:
    """Classify a YouTube URL as 'video' or 'playlist'.

    Returns:
        ("playlist", url) for playlist URLs
        ("video", video_id) for single video URLs
    """
    if "/playlist" in url.split("?")[0]:
        return ("playlist", url)
    if "list=" in url and "v=" not in url:
        return ("playlist", url)
    if "v=" in url:
        return ("video", url.split("v=")[-1].split("&")[0])
    if "youtu.be/" in url:
        return ("video", url.split("youtu.be/")[-1].split("?")[0])
    return ("video", url)


def fetch_metadata(url: str) -> dict:
    """Fetch video metadata using yt-dlp."""
    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "author": info.get("uploader"),
            "description": info.get("description"),
            "duration_seconds": info.get("duration"),
            "views": info.get("view_count"),
            "url": url,
        }


def fetch_transcript(video_id: str, language: str = "en") -> list:
    """Fetch transcript using youtube-transcript-api."""
    ytt_api = YouTubeTranscriptApi()
    langs = LANGUAGE_VARIANTS.get(language, [language])
    transcript = ytt_api.fetch(video_id, languages=langs)
    return transcript.to_raw_data()


def fetch_playlist_entries(url: str) -> tuple[dict, list[dict]]:
    """Enumerate videos in a playlist without downloading.

    Returns:
        (playlist_meta, entries) where playlist_meta has title/author/url/video_count
        and entries is a list of dicts with video_id, title, duration_seconds, url.
    """
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = []
    for entry in info.get("entries", []):
        if entry is None:
            continue
        video_id = entry.get("id", "")
        entries.append({
            "video_id": video_id,
            "title": entry.get("title"),
            "duration_seconds": entry.get("duration"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })

    playlist_meta = {
        "title": info.get("title"),
        "author": info.get("uploader"),
        "url": url,
        "video_count": len(entries),
    }
    return playlist_meta, entries


def process_single(
    url: str, video_id: str, language: str, output_dir: str | None = None
) -> dict:
    """Fetch a single video's metadata and transcript.

    If output_dir is provided, writes result to {video_id}.json in that directory.
    Returns the result dict.
    """
    result = {"metadata": None, "transcript": None, "error": None}

    try:
        result["metadata"] = fetch_metadata(url)
    except Exception as e:
        result["error"] = f"Metadata error: {e}"

    try:
        result["transcript"] = fetch_transcript(video_id, language)
    except Exception as e:
        err = f"Transcript error: {e}"
        result["error"] = err if result["error"] is None else f"{result['error']}; {err}"

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{video_id}.json")
        with open(path, "w") as f:
            json.dump(result, f, indent=2)

    return result


def process_playlist(
    url: str, output_dir: str, language: str, list_only: bool
) -> dict:
    """Process a playlist: enumerate videos, optionally fetch transcripts.

    Writes manifest.json (and per-video JSON files unless list_only) to output_dir.
    Returns the manifest dict.
    """
    os.makedirs(output_dir, exist_ok=True)

    print("Enumerating playlist...", file=sys.stderr)
    playlist_meta, entries = fetch_playlist_entries(url)
    print(f"Found {playlist_meta['video_count']} videos", file=sys.stderr)

    videos = []
    for entry in entries:
        video = {
            "video_id": entry["video_id"],
            "title": entry["title"],
            "duration_seconds": entry["duration_seconds"],
            "url": entry["url"],
            "transcript_file": f"{entry['video_id']}.json",
            "status": "skipped" if list_only else "pending",
        }
        videos.append(video)

    if not list_only:
        for i, video in enumerate(videos):
            vid = video["video_id"]
            print(f"[{i + 1}/{len(videos)}] {video['title']}", file=sys.stderr)
            try:
                result = process_single(video["url"], vid, language, output_dir)
                video["status"] = "error" if result.get("error") else "ok"
                if result.get("error"):
                    video["error"] = result["error"]
            except Exception as e:
                video["status"] = "error"
                video["error"] = str(e)

    manifest = {"playlist": playlist_meta, "videos": videos}
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch YouTube video transcript and metadata."
    )
    parser.add_argument("url", help="YouTube video or playlist URL")
    parser.add_argument(
        "-l", "--language", default="en",
        help="BCP-47 language code for transcripts (default: en)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Directory for output files (auto-created for playlists if omitted)",
    )
    parser.add_argument(
        "--list-only", action="store_true",
        help="Playlist mode: write manifest only, skip transcript fetching",
    )
    return parser


def main():
    # Backward compat: `fetch.py <url> <language>` → `fetch.py <url> -l <language>`
    if len(sys.argv) == 3 and not sys.argv[2].startswith("-"):
        sys.argv = [sys.argv[0], sys.argv[1], "-l", sys.argv[2]]

    args = build_parser().parse_args()
    url_type, identifier = parse_url(args.url)

    if url_type == "playlist":
        output_dir = args.output_dir
        if not output_dir:
            output_dir = tempfile.mkdtemp(prefix="yt-playlist-")
            print(f"Output directory: {output_dir}", file=sys.stderr)
        manifest = process_playlist(args.url, output_dir, args.language, args.list_only)
        print(json.dumps(manifest, indent=2))
    else:
        result = process_single(args.url, identifier, args.language, args.output_dir)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
