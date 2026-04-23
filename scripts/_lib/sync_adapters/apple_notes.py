"""Apple Notes sync adapter.

Pushes a workspace markdown file into Notes.app via `osascript`. The note is
created (or updated in place) inside the configured folder of the default
account. Markdown is rendered to the simple HTML-like subset Notes accepts.

Config shape (from frontmatter):
    {"folder": "Trips", "note": "Japan Packing"}

If `note` is absent, falls back to the filename stem title-cased.
"""
from __future__ import annotations

import html as _html
import re
import subprocess
from pathlib import Path

from scripts._lib.frontmatter import parse


def _md_line_to_html(line: str) -> str:
    """Render a single markdown line into the Notes-flavored HTML subset."""
    stripped = line.rstrip()
    if not stripped:
        return "<div><br></div>"

    m = re.match(r"^(\s*)- \[( |x|X)\] (.*)$", stripped)
    if m:
        checked = m.group(2).lower() == "x"
        text = _html.escape(m.group(3))
        attr = ' checked="checked"' if checked else ""
        return f'<div><input type="checkbox"{attr}>{text}</div>'

    m = re.match(r"^(\s*)[-*] (.*)$", stripped)
    if m:
        text = _html.escape(m.group(2))
        return f"<div>&bull; {text}</div>"

    m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if m:
        level = len(m.group(1))
        text = _html.escape(m.group(2))
        tag = "h1" if level == 1 else ("h2" if level == 2 else "h3")
        return f"<div><{tag}>{text}</{tag}></div>"

    return f"<div>{_html.escape(stripped)}</div>"


def _markdown_to_notes_html(body: str, title: str) -> str:
    lines = body.splitlines()
    rendered = [f"<h1>{_html.escape(title)}</h1>"]
    rendered.extend(_md_line_to_html(line) for line in lines)
    return "".join(rendered)


def _escape_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


_SCRIPT = r'''
on run argv
    set folderName to item 1 of argv
    set noteName to item 2 of argv
    set noteBody to item 3 of argv
    tell application "Notes"
        tell default account
            if not (exists folder folderName) then
                make new folder with properties {name:folderName}
            end if
            set tgt to folder folderName
            set matches to (notes of tgt whose name is noteName)
            if (count of matches) is 0 then
                make new note at tgt with properties {name:noteName, body:noteBody}
            else
                set body of (item 1 of matches) to noteBody
            end if
        end tell
    end tell
end run
'''


class AppleNotesAdapter:
    def push(self, file_path: str, config: dict) -> dict:
        path = Path(file_path)
        try:
            text = path.read_text()
        except OSError as e:
            return {"pushed": 0, "errors": [f"{path}: read failed: {e}"]}

        _fm, body = parse(text)
        folder = config.get("folder") or "lazyhuman"
        note = config.get("note") or path.stem.replace("-", " ").replace("_", " ").title()
        html = _markdown_to_notes_html(body, note)

        try:
            subprocess.run(
                ["osascript", "-e", _SCRIPT, folder, note, html],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or "osascript failed"
            return {"pushed": 0, "errors": [f"{path}: {stderr}"]}
        except FileNotFoundError:
            return {"pushed": 0, "errors": [f"{path}: osascript not found"]}

        return {"pushed": 1, "errors": []}
