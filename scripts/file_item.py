"""Close the loop on a single capture.

Usage:
    python3 -m scripts.file_item --id <capture-id> \
        [--filed-to <path> [<path> ...]] \
        [--day YYYY-MM-DD]

Effects:
  1. Read `gm_msgid` from `<local_inbox_dir>/<day>/<id>/meta.json`.
  2. Delete the staging folder.
  3. Gmail: move the message from `labels.inbox` to `labels.processed`.

The capture is now fully represented by (a) any workspace file(s) the
caller wrote and (b) the Gmail message under `lazyhuman/processed`.
No local archive is kept.

`--filed-to` is accepted (for forward-compat logging) but currently unused.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from scripts._lib.config import load_config
from scripts._lib.gmail_client import imap_session, move_by_gm_msgid


def _find_capture(inbox_dir: Path, capture_id: str, day: str | None) -> Path:
    if day:
        candidate = inbox_dir / day / capture_id
        if (candidate / "meta.json").exists():
            return candidate
        raise SystemExit(f"capture not found: {candidate}")
    if not inbox_dir.exists():
        raise SystemExit(f"local_inbox_dir does not exist: {inbox_dir}")
    matches = [
        d
        for d in inbox_dir.glob("*/" + capture_id)
        if (d / "meta.json").exists()
    ]
    if not matches:
        raise SystemExit(
            f"capture {capture_id} not found under {inbox_dir}"
        )
    if len(matches) > 1:
        raise SystemExit(
            f"ambiguous capture id {capture_id}: {[str(m) for m in matches]}"
        )
    return matches[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--filed-to", nargs="*", default=[])
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (optional)")
    args = ap.parse_args()

    cfg = load_config()
    inbox_dir = Path(cfg["local_inbox_dir"])
    src_label = cfg["labels"]["inbox"]
    dst_label = cfg["labels"]["processed"]

    src = _find_capture(inbox_dir, args.id, args.day)
    meta = json.loads((src / "meta.json").read_text())
    gm_msgid = meta.get("gm_msgid")

    shutil.rmtree(src)

    if gm_msgid is None:
        print(
            f"WARN: capture {args.id} has no gm_msgid; staging deleted but "
            f"Gmail label not flipped",
            file=sys.stderr,
        )
        return 0

    try:
        with imap_session() as conn:
            moved = move_by_gm_msgid(conn, int(gm_msgid), src_label, dst_label)
        if not moved:
            print(
                f"NOTE: gm_msgid={gm_msgid} not found in {src_label} "
                f"(already re-labeled?)",
                file=sys.stderr,
            )
    except Exception as e:  # noqa: BLE001
        print(
            f"ERROR: IMAP label move failed for gm_msgid={gm_msgid}: {e}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
