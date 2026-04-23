---
name: youtube-fetch
description: Fetch transcript and metadata from YouTube videos or playlists. Use when the user provides a YouTube link and wants to analyze, summarize, or extract information from one or more videos.
---

Note: If you have `watch-youtube` Skill, consider asking the user if they should fully watch the video or if just fetching the transcript would be sufficient for their needs.

# YouTube Fetch

Fetches transcript and metadata from YouTube videos and playlists.

## When to Use

- User shares a YouTube URL and wants to understand the content
- User asks to summarize, analyze, or extract information from a video
- User wants transcript text for further processing
- User shares a playlist URL and wants to process multiple videos

## Usage

### Single Video

```bash
python scripts/fetch.py "<youtube_url>"
python scripts/fetch.py "<youtube_url>" -l es
```

Outputs JSON to stdout with `metadata`, `transcript`, and `error` fields.

### Playlist — Fetch All Transcripts

```bash
python scripts/fetch.py "<playlist_url>" -o /tmp/my-playlist
```

Enumerates all videos in the playlist, fetches metadata and transcripts for each, and writes per-video JSON files plus a `manifest.json` to the output directory.

### Playlist — List Only (Lazy Workflow)

```bash
# Step 1: Get the manifest without fetching transcripts
python scripts/fetch.py "<playlist_url>" -o /tmp/my-playlist --list-only

# Step 2: Fetch individual videos on demand
python scripts/fetch.py "https://youtube.com/watch?v=VIDEO_ID" -o /tmp/my-playlist
```

Use `--list-only` to get a table of contents first, then fetch specific videos as needed. Useful for large playlists where you only need a subset of transcripts.

## Flags

| Flag | Description |
|------|-------------|
| `-l`, `--language` | BCP-47 language code for transcripts (default: `en`) |
| `-o`, `--output-dir` | Directory for output files (auto-created for playlists if omitted) |
| `--list-only` | Playlist mode: write manifest only, skip transcript fetching |

## Output

### Single Video (stdout)

```json
{
  "metadata": { "title": "...", "author": "...", "description": "...", "duration_seconds": 600, "views": 1000, "url": "..." },
  "transcript": [{ "text": "...", "start": 0.0, "duration": 3.5 }],
  "error": null
}
```

### Playlist (output directory)

```
<output-dir>/
  manifest.json
  <video_id_1>.json
  <video_id_2>.json
  ...
```

The manifest is also printed to stdout. Each per-video JSON file has the same format as single-video output.

**manifest.json**:

```json
{
  "playlist": { "title": "...", "author": "...", "url": "...", "video_count": 42 },
  "videos": [
    {
      "video_id": "abc123",
      "title": "...",
      "duration_seconds": 360,
      "url": "https://youtube.com/watch?v=abc123",
      "transcript_file": "abc123.json",
      "status": "ok"
    }
  ]
}
```

Video status values: `ok`, `error` (with `error` field), `skipped` (when `--list-only`).

## Examples

```bash
# Single video, English (default)
python scripts/fetch.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Single video, Spanish
python scripts/fetch.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -l es

# Playlist, fetch all
python scripts/fetch.py "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf" -o /tmp/playlist

# Playlist, manifest only
python scripts/fetch.py "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf" -o /tmp/playlist --list-only

# Legacy positional language arg still works
python scripts/fetch.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" ja
```

## Requirements

Requires `youtube-transcript-api` and `yt-dlp` packages:

```bash
pip install youtube-transcript-api yt-dlp
```
