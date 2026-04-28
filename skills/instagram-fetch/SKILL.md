---
name: instagram-fetch
description: Fetch caption and transcribe audio from Instagram reels, posts, or IGTV. Use when the user shares an Instagram link and wants to read, summarize, or extract information from a video they cannot watch right now.
---

# Instagram Fetch

Downloads a public Instagram reel/post/IGTV via `yt-dlp`, extracts the caption as `description`, and transcribes the audio locally with `faster-whisper`. Output mirrors the `youtube-fetch` skill's shape so callers (notably `/process-inbox`) can treat both the same way.

## When to Use

- User shares an Instagram URL and wants the caption + spoken content.
- A reel link arrives via the share-sheet / inbox pipeline.
- User wants to summarize or excerpt a reel without opening Instagram.

## Usage

```bash
python scripts/fetch.py "<instagram_url>"
python scripts/fetch.py "<instagram_url>" -o /tmp/ig
python scripts/fetch.py "<instagram_url>" -m tiny -l en
```

Output: JSON to stdout with `metadata`, `transcript`, and `error` fields. With `-o`, also writes `<shortcode>.json` into the directory.

## Flags

| Flag | Description |
|------|-------------|
| `-o`, `--output-dir` | Directory for `<shortcode>.json` (in addition to stdout) |
| `-m`, `--model` | faster-whisper model: `tiny`, `base`, `small` (default), `medium`, `large-v3` |
| `-l`, `--language` | BCP-47 language hint (default: auto-detect) |
| `--cookies-from-browser` | Pass-through to yt-dlp (e.g. `safari`, `chrome`) for login-required posts. The default path is public-only. |

## Output

```json
{
  "metadata": {
    "title": "first line of caption (or '<author> reel')",
    "author": "uploader handle",
    "description": "full caption verbatim",
    "duration_seconds": 30,
    "views": null,
    "upload_date": "20260301",
    "shortcode": "DXlz8jyjCxa",
    "url": "https://www.instagram.com/reel/DXlz8jyjCxa/"
  },
  "transcript": [
    {"text": "...", "start": 0.0, "duration": 2.4}
  ],
  "error": null
}
```

Failure modes:
- `error: "no video track"` — the URL points to an image-only carousel/post; `transcript: []` but `metadata.description` is still populated.
- `error: "no audio track"` — silent video; `transcript: []`.
- `error: "Metadata/download error: ..."` — yt-dlp failed (private post, removed, network). `metadata: null`.
- `error: "Transcript error: ..."` — Whisper failed; `metadata` is preserved so the caption is still usable.

Exit code is `0` when `error` is `null`, `1` otherwise.

## Requirements

```bash
pip install yt-dlp faster-whisper
brew install ffmpeg
```

`ffmpeg` and `ffprobe` must be on PATH. The first run downloads the chosen Whisper model (`small` ≈ 460MB, cached under `~/.cache/huggingface`).
