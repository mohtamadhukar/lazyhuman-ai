"""Print a short human digest of the last /process-inbox run.

Reads `<local_inbox_dir>/.last-run.json` (written by the /process-inbox
command at end of run).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts._lib.config import load_config


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "?"
    # accept either ISO Z or plain
    return ts.replace("T", " ").replace("Z", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last-run", action="store_true", default=True)
    ap.parse_args()

    cfg = load_config()
    state = Path(cfg["local_inbox_dir"]) / ".last-run.json"
    if not state.exists():
        print("(no previous run)")
        return 0

    data = json.loads(state.read_text())
    items = data.get("items", [])
    started = _fmt_ts(data.get("started_at"))
    finished = _fmt_ts(data.get("finished_at"))

    by_disp: dict[str, int] = {}
    new_files: set[str] = set()
    for it in items:
        disp = it.get("disposition") or "unknown"
        by_disp[disp] = by_disp.get(disp, 0) + 1
        for p in it.get("filed_to") or []:
            new_files.add(p)

    print(f"== lazyhuman digest ({finished or started}) ==")
    print(f"Processed: {by_disp.get('processed', 0)}")
    print(f"Dropped:   {by_disp.get('dropped', 0)}")
    print(f"Skipped:   {by_disp.get('skipped', 0)}  (will re-surface next run)")
    print(f"Failed:    {by_disp.get('failed', 0)}")
    if new_files:
        print(f"Touched files: {len(new_files)}")
        for p in sorted(new_files):
            print(f"  - {p}")
    sync = data.get("sync") or {}
    if sync:
        print("Sync:")
        for target, stats in sync.items():
            pushed = stats.get("pushed", 0)
            errors = stats.get("errors", 0)
            if isinstance(errors, list):
                errors = len(errors)
            print(f"  {target}: {pushed} pushed, {errors} errors")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
