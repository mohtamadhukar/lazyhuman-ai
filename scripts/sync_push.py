"""Push workspace files to their declared sync targets.

Usage:
    python3 -m scripts.sync_push --touched-files <path> [<path> ...]
    python3 -m scripts.sync_push --all

Each markdown file's YAML frontmatter may declare:

    sync:
      - apple-notes:
          folder: Trips
          note: Japan Packing

The entry key names an adapter in `scripts._lib.sync_adapters.REGISTRY`; the
value is the adapter config. Files without a `sync:` block are skipped.

stdout: JSON summary keyed by target:
    {"apple-notes": {"pushed": 3, "errors": []}}

A per-file failure appends to that target's `errors` list but doesn't abort
the run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts._lib.config import load_config
from scripts._lib.frontmatter import parse
from scripts._lib.sync_adapters import REGISTRY


def _iter_sync_entries(fm: dict):
    """Yield (target, config) pairs from a file's sync frontmatter."""
    raw = fm.get("sync")
    if not raw:
        return
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        (target, config), = entry.items()
        if not isinstance(config, dict):
            config = {}
        yield target, config


def _collect_files(args, workspace_dir: Path) -> list[Path]:
    if args.all:
        return sorted(workspace_dir.rglob("*.md"))
    return [Path(p) for p in args.touched_files]


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--touched-files", nargs="+", default=[])
    group.add_argument("--all", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    workspace_dir = Path(cfg["workspace_dir"])
    files = _collect_files(args, workspace_dir)

    summary: dict[str, dict] = {}
    adapters: dict[str, object] = {}

    for path in files:
        if not path.exists():
            continue
        try:
            text = path.read_text()
        except OSError as e:
            summary.setdefault("_read", {"pushed": 0, "errors": []})["errors"].append(
                f"{path}: {e}"
            )
            continue

        fm, _body = parse(text)
        for target, config in _iter_sync_entries(fm):
            bucket = summary.setdefault(target, {"pushed": 0, "errors": []})

            cls = REGISTRY.get(target)
            if cls is None:
                bucket["errors"].append(f"{path}: unknown sync target '{target}'")
                continue

            adapter = adapters.setdefault(target, cls())
            result = adapter.push(str(path), config)
            bucket["pushed"] += int(result.get("pushed", 0))
            bucket["errors"].extend(result.get("errors") or [])

    json.dump(summary, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
