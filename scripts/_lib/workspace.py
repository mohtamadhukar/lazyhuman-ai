"""Workspace init helper.

`ensure_workspace()` creates `<workspace_dir>/` and copies the starter
`CLAUDE.md` from `templates/` if the workspace doesn't have one yet.
Call this at the top of pipeline entry points (e.g. `drain_gmail.py`)
so Claude's reasoning always has a workspace + CLAUDE.md to read.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from scripts._lib.config import load_config, plugin_root


def ensure_workspace() -> Path:
    cfg = load_config()
    ws = Path(cfg["workspace_dir"])
    ws.mkdir(parents=True, exist_ok=True)
    claude_md = ws / "CLAUDE.md"
    if not claude_md.exists():
        template = plugin_root() / "templates" / "workspace-CLAUDE.md"
        shutil.copy(template, claude_md)
    return ws
