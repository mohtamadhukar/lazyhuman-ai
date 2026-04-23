"""Drain Gmail captures into the local staging folder.

Usage:
    python3 -m scripts.drain_gmail

Reads every message under the configured `labels.inbox` Gmail label
over IMAP, and writes each as `<local_inbox_dir>/<YYYY-MM-DD>/<id>/`
containing:
    meta.json     augmented metadata (includes gm_msgid)
    payload[.ext] user-intended payload(s), if any

Gmail is the source of truth; no local `.eml` snapshot is kept. The
staging folder is ephemeral — deleted by `file_item.py` on filing.

Non-destructive: does NOT modify labels. `file_item.py` owns label
transitions.

stdout: JSON array of `{id, folder, kind, source_url, hint}`.
"""
from __future__ import annotations

import html
import json
import mimetypes
import re
import sys
from datetime import date
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from scripts._lib.config import load_config
from scripts._lib.gmail_client import fetch_rfc822, imap_session, list_uids
from scripts._lib.workspace import ensure_workspace

JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
QUOTE_PREFIX = re.compile(r"(?m)^\s*>+\s?")


def _strip_quote_markers(text: str) -> str:
    """Remove leading `> ` quote markers (Apple Mail share sheet, reply quotes)."""
    return QUOTE_PREFIX.sub("", text)

UNRELIABLE_URL_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
}


def _parse_meta(text_body: str) -> dict:
    m = JSON_BLOCK.search(text_body)
    if not m:
        m = JSON_BLOCK.search(_strip_quote_markers(text_body))
    if not m:
        raise ValueError("no ```json meta block found in email body")
    return json.loads(m.group(1))


def _extract_body_and_attachments(
    msg: EmailMessage,
) -> tuple[str, list[tuple[str, str, bytes]]]:
    """Walk parts; return (text_body, [(filename, mime_type, bytes), ...])."""
    text_plain: str | None = None
    text_html: str | None = None
    attachments: list[tuple[str, str, bytes]] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename:
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:  # noqa: BLE001
                payload = b""
            if payload:
                attachments.append((filename, ctype, payload))
            continue
        if ctype == "text/plain" and text_plain is None:
            try:
                text_plain = part.get_content()
            except Exception:  # noqa: BLE001
                raw = part.get_payload(decode=True) or b""
                text_plain = raw.decode("utf-8", errors="replace")
        elif ctype == "text/html" and text_html is None:
            try:
                text_html = part.get_content()
            except Exception:  # noqa: BLE001
                raw = part.get_payload(decode=True) or b""
                text_html = raw.decode("utf-8", errors="replace")

    if text_plain is not None:
        body = text_plain
    elif text_html is not None:
        body = html.unescape(re.sub(r"<[^>]+>", "", text_html))
    else:
        body = ""
    return body, attachments


def _derive_ext(filename: str | None, mime_type: str) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    return mimetypes.guess_extension(mime_type or "") or ""


def infer_kind(meta: dict, attachment_mimes: list[str], body_text: str) -> str:
    if meta.get("source_url"):
        return "url"
    for mt in attachment_mimes:
        if mt.startswith("image/"):
            return "image"
        if mt == "application/pdf":
            return "pdf"
        if mt.startswith("audio/"):
            return "audio"
    if body_text.strip():
        return "text"
    return "unknown"


def should_keep_attachments(source_url: str | None) -> bool:
    if not source_url:
        return True
    host = urlparse(source_url).netloc.lower()
    return host in UNRELIABLE_URL_HOSTS


def _captured_day(meta: dict) -> str:
    ts = meta.get("captured_at", "")
    if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        return ts[:10]
    return date.today().isoformat()


def _process_raw(
    raw: bytes, gm_msgid: int | None, inbox_dir: Path
) -> dict | None:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)
    text_body, attachments = _extract_body_and_attachments(msg)

    try:
        meta = _parse_meta(text_body)
    except (ValueError, json.JSONDecodeError) as e:
        print(
            f"WARN: gm_msgid={gm_msgid} has no valid meta block ({e}); "
            f"leaving in lazyhuman/inbox for next drain",
            file=sys.stderr,
        )
        return None

    capture_id = meta.get("id")
    if not capture_id:
        print(
            f"WARN: gm_msgid={gm_msgid} meta missing id; skipping", file=sys.stderr
        )
        return None

    day = _captured_day(meta)
    folder = inbox_dir / day / capture_id
    folder.mkdir(parents=True, exist_ok=True)

    attachment_mimes = [mt for _, mt, _ in attachments]
    if meta.get("kind") in (None, "", "auto"):
        meta["kind"] = infer_kind(meta, attachment_mimes, text_body)

    keep = should_keep_attachments(meta.get("source_url"))
    written: list[str] = []
    if keep and attachments:
        for idx, (filename, mt, payload) in enumerate(attachments):
            ext = _derive_ext(filename, mt)
            base = "payload" if len(attachments) == 1 else f"payload-{idx}"
            out_name = f"{base}{ext}"
            (folder / out_name).write_bytes(payload)
            written.append(out_name)

    meta["gm_msgid"] = gm_msgid
    meta["attachments"] = written

    (folder / "meta.json").write_text(json.dumps(meta, indent=2))

    return {
        "id": capture_id,
        "folder": str(folder),
        "kind": meta["kind"],
        "source_url": meta.get("source_url"),
        "hint": meta.get("hint"),
    }


def main() -> int:
    cfg = load_config()
    ensure_workspace()
    inbox_dir = Path(cfg["local_inbox_dir"])
    inbox_dir.mkdir(parents=True, exist_ok=True)
    label = cfg["labels"]["inbox"]

    manifest: list[dict] = []
    seen: set[str] = set()

    with imap_session() as conn:
        uids = list_uids(conn, label)
        for uid in uids:
            try:
                raw, gm_msgid = fetch_rfc822(conn, uid)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: fetch uid={uid} failed: {e}", file=sys.stderr)
                continue
            if not raw:
                continue
            entry = _process_raw(raw, gm_msgid, inbox_dir)
            if entry is None:
                continue
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            manifest.append(entry)

    json.dump(manifest, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
