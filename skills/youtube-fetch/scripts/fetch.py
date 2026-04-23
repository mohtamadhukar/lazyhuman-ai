#!/usr/bin/env python3
"""Fetch YouTube video transcript and metadata. Supports single videos and playlists."""

import argparse
import json
import os
import sys
import tempfile

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi


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
