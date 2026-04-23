"""Tiny YAML frontmatter parser/renderer for workspace markdown files.

`parse(text) -> (dict, body)` — empty dict if no frontmatter.
`render(fm, body) -> text` — no fences when fm is empty.
"""
from __future__ import annotations

import re

import yaml

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


def parse(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group(2)


def render(fm: dict, body: str) -> str:
    if not fm:
        return body
    dumped = yaml.safe_dump(fm, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n{body}"
