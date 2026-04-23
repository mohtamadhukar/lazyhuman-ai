# Implementation Plan: lazyhuman-ai

## References

- **Requirements:** [2026-04-23-REQUIREMENTS-lazyhuman-ai.md](./2026-04-23-REQUIREMENTS-lazyhuman-ai.md)
- **Design:** [2026-04-23-DESIGN-lazyhuman-ai.md](./2026-04-23-DESIGN-lazyhuman-ai.md)

## Overview

Build the lazyhuman-ai Claude Code plugin: an iOS→Gmail capture pipeline that drains pending emails, lets Claude extract/categorize each capture into a local Markdown workspace, then pushes touched files out to Apple Notes. Greenfield — this repo currently has only `docs/plans/`.

## Implementation Order

The plan is ordered so that each phase produces something runnable end-to-end as early as possible:

1. **Phase 1** — plugin skeleton + config/secrets plumbing. **[done]**
2. **Phase 2** — Gmail auth + drain (app-password IMAP; no OAuth). **[done]**
3. **Phase 3** — filing + digest (closes the capture lifecycle; deletes staging on filing, no local archive). **[done]**
4. **Phase 4** — vendor the two colleague skills so Claude has YouTube + PDF extractors available. **[done — live run pending `pip install -r requirements.txt`]**
5. **Phase 5** — the `/process-inbox` command prompt + starter workspace template (wires Claude's semantic work into the pipeline). **[done]**
6. **Phase 6** — sync layer (frontmatter + Apple Notes adapter + `sync_push.py` + `/sync-outputs` command). **[done — Apple Notes live push untested]**
7. **Phase 7** — iOS Shortcut + Gmail filter setup docs (the user-facing install path). **[done]**
8. **Phase 8** — end-to-end dry-run + hardening. **[in progress — digest/docstring cleanup done; live smoke tests pending]**

---

## Phase 1: Plugin Skeleton & Config Plumbing

Goal: empty-but-valid Claude Code plugin with config loading, `.env` secret plumbing, and a gitignore in place.

### Step 1.1: Create plugin manifest and repo hygiene

**Status:** `[x]` done

**Files:**
- `.claude-plugin/plugin.json` — plugin metadata
- `.gitignore` — ignores `config.json`, `credentials.json`, `.env`, `__pycache__/`, `.DS_Store`, `*.pyc`, `.venv/`
- `README.md` — one-page install / usage overview
- `config.example.json` — matches DESIGN §9
- `.env.example` — placeholder for `GMAIL_APP_PASSWORD`

**Implementation:**
- `plugin.json` fields: `name: "lazyhuman-ai"`, `version: "0.1.0"`, `description`, `author`.
- `config.example.json`:
  ```json
  {
    "workspace_dir": "~/LocalDocuments/lazyhuman-workspace",
    "local_inbox_dir": "~/LocalDocuments/lazyhuman-inbox",
    "gmail_address": "<your>@gmail.com",
    "labels": {
      "inbox": "lazyhuman/inbox",
      "processed": "lazyhuman/processed"
    }
  }
  ```
- `.gitignore`:
  ```
  config.json
  credentials.json
  .env
  __pycache__/
  *.pyc
  .DS_Store
  .venv/
  ```
- `.env.example`: contains `GMAIL_APP_PASSWORD=` (empty value).

**Verification:**
- [x] `plugin.json` / `config.example.json` are valid JSON.
- [x] `.gitignore` prevents `config.json`, `credentials.json`, and `.env` from being tracked.

---

### Step 1.2: Implement `scripts/_lib/config.py`

**Status:** `[x]` done

**Files:**
- `scripts/_lib/__init__.py` — empty
- `scripts/_lib/config.py` — config + `.env` loader (no Keychain, no external dotenv lib)

**Implementation:** `load_config()` reads `config.json` from the plugin root and expands `~` in path fields. `load_gmail_secret()` reads a `GMAIL_APP_PASSWORD` from `.env` (via a tiny inline dotenv loader) or the real environment, and returns `{"app_password": <pw>}`. No macOS Keychain dependency.

**Verification:**
- [x] `from scripts._lib.config import load_config, load_gmail_secret` both resolve with the repo's `config.json` + `.env`.
- [x] Missing secret surfaces a clear error pointing at `.env.example`.

---

## Phase 2: Gmail Auth & Drain

Goal: a working `drain_gmail.py` that pulls real emails from the `lazyhuman/inbox` label, writes them as local staging folders, and returns a JSON manifest.

**Auth pivot note:** the original design used OAuth + Google API. During implementation we pivoted to **IMAP + Gmail app password** (simpler setup; no Google Cloud project needed). All code in Phase 2 reflects the IMAP approach.

### Step 2.1: Secret loading (app password via `.env`)

**Status:** `[x]` done — folded into Step 1.2

No separate setup script. User enables 2-Step Verification, creates a Gmail app password, enables IMAP, and pastes the 16-char password into `.env` as `GMAIL_APP_PASSWORD`. `load_gmail_secret()` (Step 1.2) reads it. `docs/gmail-setup.md` documents the browser flow.

**Verification:**
- [x] `docs/gmail-setup.md` describes the app-password + IMAP setup.
- [x] `.env` secret is picked up by `load_gmail_secret()`.

---

### Step 2.2: Gmail client wrapper (IMAP)

**Status:** `[x]` done

**Files:**
- `scripts/_lib/gmail_client.py`

**Implementation:** IMAP wrapper over `imapclient`. Exposes:
- `imap_connect()` / `imap_session()` — context manager that logs into `imap.gmail.com` with `(gmail_address, app_password)`.
- `list_uids(conn, folder)` — select a Gmail label ("folder") and return all UIDs.
- `fetch_rfc822(conn, uid)` — fetch raw RFC822 + `X-GM-MSGID` (Gmail's stable 64-bit message id that survives label changes).
- `find_uid_by_gm_msgid(conn, folder, gm_msgid)` — re-locate a message across sessions.
- `move_by_gm_msgid(conn, gm_msgid, src_folder, dst_folder)` — Gmail IMAP `MOVE`, which semantically swaps the label while preserving any others.

**Verification:**
- [x] `imap_session()` logs in cleanly with the app password from `.env`.
- [x] `list_uids(conn, "lazyhuman/inbox")` returns UIDs for live messages under that label.

---

### Step 2.3: `drain_gmail.py`

**Status:** `[x]` done

**Files:**
- `scripts/drain_gmail.py`

**Implementation:**
- `imap_session()` → `list_uids(conn, cfg['labels']['inbox'])` → for each UID `fetch_rfc822(conn, uid)` returning `(raw_bytes, gm_msgid)`.
- Parse RFC822 with stdlib `email` (`BytesParser(policy=policy.default)`). Walk MIME parts:
  - Preferred body: `text/plain`; fallback: `text/html` → strip tags + `html.unescape()` (needed because iOS Mail sends HTML-only bodies with `&quot;` entities, which otherwise break the JSON regex).
  - Attachments: any part with a filename and non-text MIME type, decoded via `get_payload(decode=True)`.
- Extract ```json ... ``` fenced block from the body → `meta` dict.
- **Infer `kind`** from MIME if `meta["kind"] == "auto"` (Shortcut sets `auto`; drain is authoritative). Logic: `source_url` → `url`; else first attachment mime maps to `image`/`pdf`/`audio`; else body text → `text`; else `unknown`.
- **Drop junk attachments for reliable URL sources.** If `source_url` is set and the host is NOT in `UNRELIABLE_URL_HOSTS` (Instagram/TikTok), skip writing any attachment — they're page-preview junk (favicons, OG images) that iOS attaches to URL shares. For Instagram/TikTok, keep them (vision often needs the screenshot).
- Write `<local_inbox_dir>/<day>/<id>/meta.json` + any surviving `payload[.ext]`. Folder is ephemeral (deleted by `file_item.py`). **No `email_snapshot.eml`** — Gmail is the source of truth; `gm_msgid` is the re-fetch handle.
- Augment meta with `gm_msgid` and `attachments` (the list of filenames written). No `status`/`disposition`/`processed_at`/`filed_to` — those were archive-era fields.
- **Do NOT modify labels here.** `file_item.py` owns label transitions. Drain is non-destructive; messages that fail to parse stay in `lazyhuman/inbox` and re-surface next run.
- stdout: JSON array `[{id, folder, kind, source_url, hint}, ...]`.

**Verification:**
- [x] Sent real test captures; drain wrote `meta.json` + `payload.PNG` only (no `.eml`).
- [x] Meta parses correctly from HTML-only iOS Mail bodies (the `html.unescape` fix).
- [x] `kind` inferred correctly for image and text captures.
- [x] Gmail label unchanged after drain; second run is idempotent.

---

## Phase 3: Filing & Digest

Goal: close the lifecycle loop. Given a drained capture, `file_item.py` deletes the staging folder and flips the Gmail label to `processed`. No local archive is kept — Gmail is the authoritative store.

### Step 3.1: `file_item.py`

**Status:** `[x]` done

**Files:**
- `scripts/file_item.py` — create

**Implementation:**
- CLI args: `--id <capture-id> [--filed-to <path> ...] [--day YYYY-MM-DD]`. `--filed-to` is accepted for forward-compat logging but currently unused.
- Side effects:
  1. Locate capture folder at `<local_inbox_dir>/<day>/<id>/` (scan all day folders if `--day` absent).
  2. Read `meta.json` → extract `gm_msgid`.
  3. `shutil.rmtree(src)` — delete the staging folder.
  4. Gmail: `move_by_gm_msgid(conn, gm_msgid, labels.inbox, labels.processed)` via IMAP. In Gmail, MOVE swaps the label while preserving any others.
- Exit 0 on success; 2 on Gmail API error (staging already deleted by that point — next drain will re-surface the message because the label wasn't flipped, and Claude can re-file it).
- **Skipped / ambiguous / failed captures do NOT call `file_item.py`.** They stay in `lazyhuman/inbox`, re-surface on the next drain. Single-pass triage (Phase 5) resolves them inline in the same `/process-inbox` conversation.

**Verification:**
- [x] `python3 -m scripts.file_item --id <id>` on a drained capture: staging folder is deleted; Gmail message moves from `lazyhuman/inbox` → `lazyhuman/processed`.
- [x] `<workspace>/_archive/` is **not** created.
- [x] `grep -r "<id>" <workspace>` returns the workspace file where Phase 5 placed the visible source line.
- [x] Second run of `drain_gmail.py` yields no new captures for this id.

---

### Step 3.2: `digest.py`

**Status:** `[x]` done

**Files:**
- `scripts/digest.py`
- (state file) `<local_inbox_dir>/.last-run.json` — written by `/process-inbox` in Phase 5; `digest.py` reads it

**Implementation:**
- Reads `<local_inbox_dir>/.last-run.json`; prints a short human summary grouping items by disposition, listing touched files, and a per-target sync summary. No-op prints `(no previous run)` if the state file is absent.
- No references to `_review.md` (removed from the design); triage no longer accumulates across runs.

**Verification:**
- [x] Syntax-checks and imports cleanly.
- [ ] End-to-end verification deferred to Phase 5 (no `.last-run.json` produced yet).

---

## Phase 4: Vendor Colleague Skills

Goal: `skills/youtube-fetch/` and `skills/pdf-to-markdown/` live inside this repo and can be invoked as subprocesses.

### Step 4.1: Vendor `youtube-fetch` and `pdf-to-markdown`

**Status:** `[x]` done (code vendored + `requirements.txt` updated; live CLI smoke tests pending `pip install -r requirements.txt`)

**Files:**
- `skills/youtube-fetch/` — copy from `~/LocalDocuments/Github/agentic-systems/skills/youtube-fetch/`
- `skills/pdf-to-markdown/` — copy from `~/LocalDocuments/Github/agentic-systems/skills/pdf-to-markdown/`

**Implementation:**
- `cp -R ~/LocalDocuments/Github/agentic-systems/skills/youtube-fetch skills/`
- `cp -R ~/LocalDocuments/Github/agentic-systems/skills/pdf-to-markdown skills/`
- Read each skill's entry-point script to confirm the CLI shape documented in DESIGN §8 (`python skills/youtube-fetch/scripts/fetch.py <url>` and `python skills/pdf-to-markdown/scripts/convert.py <path>`). Adjust DESIGN reference or the command line used in Phase 5 if actual entry points differ.
- Add dependencies to a top-level `requirements.txt`. **Post-OAuth-pivot:** `google-api-python-client` / `google-auth-oauthlib` / `keyring` are dropped (not used by the IMAP+app-password path). Actual contents:
  ```
  imapclient>=3.0
  pyyaml>=6.0
  youtube-transcript-api>=0.6
  yt-dlp>=2024.1
  pymupdf4llm>=0.0.10
  ```

**Verification:**
- [ ] `python skills/youtube-fetch/scripts/fetch.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"` — returns JSON with `title`, `channel`, `transcript` fields. _(deferred — needs `pip install -r requirements.txt`)_
- [ ] `python skills/pdf-to-markdown/scripts/convert.py <any-small-pdf>` — returns Markdown content to stdout (or a known output path — check the skill's README). _(deferred — needs deps)_
- [x] Both skills run without reaching outside this repo (no absolute-path references back to `agentic-systems`). (grep confirmed.)

---

## Phase 5: `/process-inbox` Command + Starter Workspace Template

Goal: the slash command exists; Claude can run it end-to-end on a real capture.

### Step 5.1: Workspace starter template

**Status:** `[x]` done

**Files:**
- `templates/workspace-CLAUDE.md` — create

**Implementation:** the exact skeleton from DESIGN §7 — H2 sections for Identity, Dietary, People, Category conventions (empty, commented examples), New-file policy, Sync defaults (empty, commented examples).

**Verification:**
- [x] File exists at `templates/workspace-CLAUDE.md` and matches DESIGN §7 content.

---

### Step 5.2: Workspace init on first run

**Status:** `[x]` done (wired into `drain_gmail.py:main`)

**Files:**
- `scripts/_lib/workspace.py` — create

**Implementation:**
```python
# scripts/_lib/workspace.py
from pathlib import Path
import shutil
from scripts._lib.config import load_config, plugin_root

def ensure_workspace() -> Path:
    cfg = load_config()
    ws = Path(cfg["workspace_dir"])
    ws.mkdir(parents=True, exist_ok=True)
    claude_md = ws / "CLAUDE.md"
    if not claude_md.exists():
        shutil.copy(plugin_root() / "templates" / "workspace-CLAUDE.md", claude_md)
    return ws
```

No `_archive/` and no `_review.md` — pipeline no longer creates side-files. Just ensures the workspace root + `CLAUDE.md` exist. Call this from `drain_gmail.py` at startup so the workspace is guaranteed before any Claude reasoning begins.

**Verification:**
- [x] `ensure_workspace()` smoke-tested against the live workspace dir — returns the path, `CLAUDE.md` present. (Full "delete + recreate" pass deferred — destructive action; user should do it manually.)

---

### Step 5.3: `commands/process-inbox.md` — the slash-command prompt

**Status:** `[x]` done (prompt written; live `/process-inbox` dry-run pending)

**Files:**
- `commands/process-inbox.md` — create

**Implementation:**
The prompt drives Claude through the phases from DESIGN §3. **Single pass, inline triage** — ambiguous items are resolved in-chat at the end of the same run; there is no cross-run review queue.

1. **Drain** — Run `python scripts/drain_gmail.py`. Parse the JSON manifest on stdout.
2. **Process each item** — For each capture in the manifest:
   - Read `<folder>/meta.json` and the payload files (Read tool for text/PDF/image; WebFetch if `source_url` set and `kind == "url"`).
   - Route by `kind`:
     - `url` + YouTube domain → `python skills/youtube-fetch/scripts/fetch.py <url>`.
     - `url` + Instagram/TikTok → add to triage list (re-capture as screenshot suggested).
     - `url` (other) → WebFetch.
     - `pdf` → `python skills/pdf-to-markdown/scripts/convert.py <payload path>`.
     - `image` / `screenshot` → Read the image directly.
     - `text` → use body.
     - `audio` → add to triage list ("audio transcription Post-MVP").
   - Consult workspace `CLAUDE.md` (already in context via Claude Code harness) for Identity/Dietary/People/Sync-defaults/Category-conventions.
   - Decide target file(s) and output shape (task `- [ ]`, list bullet, freeform note). Prefer existing files; create new ones freely. For place entries, format as `- [<name>](https://maps.app.goo.gl/?q=<urlencoded name>) — <notes>`.
   - **Append a visible source line** immediately below the inserted section, as italic markdown:
     ```
     _Source: [<capture_id>](https://mail.google.com/mail/u/0/#search/subject%3A%22%5BLH%5D+<capture_id>%22) · captured <YYYY-MM-DD>_
     ```
     The link opens Gmail (web or mobile app) filtered to the exact source email via the `[LH] <id>` subject search. The `<capture_id>` is plain text so `grep -r <id> <workspace>` still locates where the capture landed.
   - When creating a new file, match against `CLAUDE.md` "Sync defaults" pattern rules and write corresponding `sync:` frontmatter. If no rule matches, leave frontmatter absent and add the file to the triage "sync confirmation" list.
   - Edit/Write the workspace file.
   - Call `python scripts/file_item.py --id <id> --filed-to <paths>`.
   - Record this item's outcome into the in-progress `.last-run.json`.
3. **Triage phase (inline, same conversation)** — For each capture Claude flagged as ambiguous, present a short summary + options and accept a free-text reply:
   - *"file under <path>, note X"* → Claude writes the file (with breadcrumb), calls `file_item.py --id <id> --filed-to <path>`.
   - *"drop"* → Claude calls `file_item.py --id <id>` with no `--filed-to` (Gmail label flips; no workspace file created).
   - *"skip"* → Claude does **nothing**. The Gmail label stays `inbox`; the capture re-surfaces on the next `/process-inbox` run.
   - Also walk the sync-confirmation list for any new files with no matched sync default.
4. **Sync push** — Run `python scripts/sync_push.py --touched-files <space-separated list>`. Parse its JSON output into `.last-run.json`'s `sync` block.
5. **Digest** — Run `python scripts/digest.py` and show the output to the user.

**Important command-prompt rules:**
- The slash-command prompt is where extraction/formatting rules live (e.g. Maps-link format, Source-line convention). `CLAUDE.md` holds user-editable facts, not formatting rules.
- On any subprocess error: add to the triage list with the specific failure reason; do NOT call `file_item.py` yet (so the capture re-surfaces next run if the user skips it in triage).
- `.last-run.json` is written by Claude at end of run (simplest path for MVP). Schema: see Step 3.2. Path: `<local_inbox_dir>/.last-run.json`.

**Verification:**
- [x] `commands/process-inbox.md` exists and contains the phase-ordered instructions above in clear prose (not pseudocode).
- [ ] Plugin reload in Claude Code exposes `/process-inbox` as a slash command. _(deferred — requires reload)_
- [ ] Dry-run: send a test email with a plain URL, run `/process-inbox`. Claude drains, WebFetches, writes a new file in the workspace (with the visible Source line), calls `file_item.py`, prints the digest. Gmail label moves to `processed`. `grep -r <id> <workspace>` finds the new file; clicking the Source link opens Gmail to that exact message. _(deferred — live capture test)_

---

## Phase 6: Sync Layer

Goal: `sync_push.py` pushes touched workspace files to Apple Notes; `/sync-outputs` can do a full resync.

### Step 6.1: Frontmatter parsing library

**Status:** `[x]` done

**Files:**
- `scripts/_lib/frontmatter.py` — create

**Implementation:**
```python
# scripts/_lib/frontmatter.py
import re
import yaml

FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)", re.DOTALL)

def parse(text: str) -> tuple[dict, str]:
    """Returns (frontmatter_dict, body). Empty dict if no frontmatter."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)

def render(fm: dict, body: str) -> str:
    if not fm:
        return body
    return f"---\n{yaml.safe_dump(fm, sort_keys=False).strip()}\n---\n{body}"
```

**Verification:**
- [x] Round-trip test: `parse(render({"sync": [{"apple-notes": {"folder": "Trips", "note": "Japan"}}]}, body))` returns identical dict + body.

---

### Step 6.2: Apple Notes sync adapter

**Status:** `[x]` code done; live Notes.app push **not yet verified** (would write to user's real Notes — do a manual pass before trusting).

**Implementation deviation:** AppleScript is invoked via `osascript -e SCRIPT folder note body` (argv), not by string-interpolating an escaped body into the script. This removes the escaping step noted in the original plan.

**Files:**
- `scripts/_lib/sync_adapters/__init__.py` — create — registry
- `scripts/_lib/sync_adapters/apple_notes.py` — create

**Implementation:**

`__init__.py`:
```python
from .apple_notes import AppleNotesAdapter

REGISTRY = {
    "apple-notes": AppleNotesAdapter,
}
```

`apple_notes.py`:
- Interface: `push(self, file_path: str, config: dict) -> dict` returning `{"pushed": int, "errors": [str]}`.
- `config` shape from frontmatter: `{"folder": "Trips", "note": "Japan Packing"}`. If `note` absent, default to filename stem title-cased.
- Read file body (strip frontmatter using `scripts._lib.frontmatter`).
- Build AppleScript:
  ```applescript
  tell application "Notes"
    set targetFolder to folder "Trips" of default account
    -- ensure folder exists; if not, create it
    set existing to notes of targetFolder whose name is "Japan Packing"
    if (count of existing) is 0 then
      make new note at targetFolder with properties {name:"Japan Packing", body:"..."}
    else
      set body of (item 1 of existing) to "..."
    end if
  end tell
  ```
- Invoke via `subprocess.run(["osascript", "-"], input=script, text=True, check=True)`.
- Escape the body for AppleScript (quotes, backslashes). Convert Markdown to simple HTML-ish text (Notes body accepts basic HTML — `<br>`, `<ul>`, `<li>`, `<input type=checkbox>` for `- [ ]`). For MVP, a naive line-by-line renderer is fine:
  - `- [ ] foo` → `<div><input type=\"checkbox\">foo</div>`
  - `- [x] foo` → `<div><input type=\"checkbox\" checked>foo</div>`
  - `- foo` → `<div>• foo</div>`
  - other lines → `<div>foo</div>`
- Return `{"pushed": 1, "errors": []}` on success, `{"pushed": 0, "errors": ["<reason>"]}` on failure.

**Verification:**
- [x] Markdown-to-Notes-HTML renderer unit-tested (checkboxes, bullets, headings, plain lines).
- [ ] Create `<workspace>/test-sync.md` with frontmatter `sync: [{apple-notes: {folder: "LH Test", note: "T1"}}]` and two task lines. _(pending)_
- [ ] Run the driver: `python3 -m scripts.sync_push --touched-files <workspace>/test-sync.md`. _(pending)_
- [ ] Notes.app shows a new folder `LH Test` containing note `T1` with the two items as checkboxes. _(pending)_
- [ ] Running again replaces the note body (no duplicate note, no duplicate items). _(pending)_

---

### Step 6.3: `sync_push.py`

**Status:** `[x]` done

**Files:**
- `scripts/sync_push.py` — create

**Implementation:**
- CLI: `--touched-files <path> [<path> ...]` OR `--all` (iterate every `.md` under `<workspace_dir>`).
- For each file:
  - Read body → `parse()`.
  - `sync` list in frontmatter? If not, skip.
  - For each entry (each is a single-key dict like `{"apple-notes": {...}}`): look up adapter in `REGISTRY`, call `adapter.push(file_path, config)`.
  - Aggregate per-target counts.
- stdout: JSON summary
  ```json
  {
    "apple-notes": {"pushed": 3, "errors": []}
  }
  ```
- Non-fatal: any single-file failure appends to that target's `errors` list and processing continues.

**Verification:**
- [ ] Multiple files with sync frontmatter → single JSON summary with aggregated counts. _(pending — needs the Apple Notes path end-to-end)_
- [x] A file that references an unknown sync target produces a clear error entry but doesn't crash the run. (Dry-run test written; confirmed `{"unknown-target": {"pushed": 0, "errors": ["<path>: unknown sync target 'unknown-target'"]}}`.)

---

### Step 6.4: `/sync-outputs` command

**Status:** `[x]` done

**Files:**
- `commands/sync-outputs.md` — create

**Implementation:** short command prompt — run `python3 -m scripts.sync_push --all`, display the JSON summary to the user.

**Verification:**
- [x] `commands/sync-outputs.md` exists and invokes the module.
- [ ] `/sync-outputs` in Claude Code runs the script and shows the summary. _(deferred — needs plugin reload)_

---

## Phase 7: iOS Shortcut + Gmail Setup Docs

Goal: a user following the docs from scratch can install and start capturing within ~30 minutes.

### Step 7.1: `docs/gmail-setup.md`

**Status:** `[x]` done (first pass — may iterate).

**Files:**
- `docs/gmail-setup.md` — create

**Content:**
- Enable 2-Step Verification on the Google account.
- Create a Gmail app password (name it `lazyhuman-ai`); copy the 16-char value.
- Enable IMAP in Gmail settings.
- Create nested labels `lazyhuman/inbox` and `lazyhuman/processed`.
- Add filter: `To: <your+lh>@gmail.com` → apply `lazyhuman/inbox`, skip inbox, also apply to existing.
- Set `gmail_address` in `config.json`, paste the app password into `.env` as `GMAIL_APP_PASSWORD`.
- Smoke test: send a matching message; run `python3 -m scripts.drain_gmail`.

**Verification:**
- [x] Followed the doc end-to-end; drain returns real captures.

---

### Step 7.2: `docs/ios-shortcut-setup.md`

**Status:** `[x]` done (first pass, with build-from-scratch walkthrough, JSON meta example, smoke tests, and common snags section).

**Files:**
- `docs/ios-shortcut-setup.md` — create

**Content:**
- Step-by-step build of the Shortcut, matching the pseudocode in DESIGN §Interface 1.
- Two invocation paths (Share Sheet vs. home-screen menu).
- Where to edit `CAPTURED_BY`.
- Adding the Shortcut icon to the home screen.
- Optional: JSON meta block examples for each `kind`.
- Screenshot placeholders (TODO; real screenshots added on first build).

**Verification:**
- [x] Build the Shortcut on the user's iPhone per the doc. (Kyoto smoke test captures confirmed working in Phase 2.)
- [x] Share a screenshot from Photos → Shortcut → email arrives in Gmail with json meta + attachment + applied label. (Confirmed in Phase 2 smoke test.)

---

## Phase 8: End-to-End Dry Run & Hardening

Goal: confidence that the full capture → process → sync loop is reliable enough for daily adoption.

### Step 8.1: End-to-end smoke tests

**Status:** `[ ]` pending

**Files:** none (documentation only — capture results in `docs/plans/` as a short test log or inline in the PR description).

**Test matrix:**
- [ ] URL capture (article) → `reading.md` entry with 3-bullet summary.
- [ ] URL capture (YouTube) → entry with title/channel/transcript-derived summary.
- [ ] URL capture (Instagram, no screenshot) → flagged in inline triage; user answers "re-capture as screenshot"; capture stays in `lazyhuman/inbox` (skipped). Confirm it re-surfaces on the next run.
- [x] Screenshot capture (reel with 6 place names) → `trips/japan/vegan-spots.md` with Maps-linked entries. (Verified manually in the Kyoto smoke test.)
- [ ] Text capture with hint "add to Japan trip" → routed to `trips/japan/notes.md`.
- [ ] PDF capture (a receipt) → extracted into an appropriate file (Claude's judgment).
- [ ] Triage phase (single-pass, inline): respond "drop" / "skip" / "file to X" each at least once.
- [ ] Sync: after a run, confirm the touched Apple Notes note reflects current file body.

---

### Step 8.2: Error-path hardening

**Status:** `[~]` partial — cleanup done; destructive-path smoke tests deferred.

**Files:**
- `scripts/digest.py` — drop `_review.md` / `needs-review` references; now prints Processed / Dropped / Skipped / Failed. **[done]**
- `scripts/drain_gmail.py` — usage docstring fixed to `python3 -m scripts.drain_gmail`; per-UID fetches already wrapped in try/except with WARN logs. **[done, pre-existing]**
- `scripts/file_item.py` — usage docstring fixed to module style; idempotency already handled (`move_by_gm_msgid` returns False with a clean "already re-labeled?" log). **[done, pre-existing]**
- `scripts/_lib/gmail_client.py` — dropped stale reference to `setup_gmail_auth.py` (file never created); IMAP login error already surfaces a clean `SystemExit` with remediation text. **[done]**
- `docs/gmail-setup.md` — smoke-test command fixed to `python3 -m scripts.drain_gmail`. **[done]**
- `commands/process-inbox.md` — documents IMAP-auth / subprocess / unknown-sync-target failure modes in its "Failure modes to handle gracefully" section. **[done]**

**Verification:**
- [ ] Kill network mid-drain → next run resumes cleanly (no orphaned folders, no duplicate captures). _(pending — destructive smoke test)_
- [ ] Manually corrupt one `meta.json` → `file_item.py` surfaces a clean error without crashing the batch. _(pending)_
- [ ] Revoke the Gmail app password → next run surfaces a clear "check `.env` / regenerate app password" message, not a stack trace. _(pending — tested logic path exists at `gmail_client.py:30-38`)_

---

## Final Verification

- [ ] `/process-inbox` runs end-to-end on ≥5 real captures without manual intervention.
- [ ] Captures meet the REQ success criteria:
  - [ ] Reel screenshot with 5 places → Maps-linked list in <60s.
  - [ ] ≤3 taps capture latency (measured on iPhone).
  - [ ] Zero silent data loss: every drained id either lands in the workspace (with visible Source line) or stays in `lazyhuman/inbox` (skipped; re-surfaces next run).
- [ ] `/sync-outputs` full-resync produces Apple Notes matching workspace files.
- [ ] `docs/gmail-setup.md` and `docs/ios-shortcut-setup.md` are followable without asking questions.
- [ ] All deltas in DESIGN are reflected in REQUIREMENTS.md (Gmail transport via IMAP + app password, vendored skills, update detection deferred, sync layer added, no local archive, single-pass inline triage).

## Notes

- **Order dependency:** Phase 5 (command prompt) depends on Phases 1–4 being runnable; Phase 6 (sync) is independent and can run in parallel with 5 if there's capacity.
- **Secrets:** the Gmail app password lives in `.env` (gitignored). `credentials.json` is not used — OAuth was swapped out for app-password IMAP.
- **Plan B (Apple Notes transport)** stays off the critical path. If Gmail proves unreliable, swap `drain_gmail.py` for `drain_notes.py` — per DESIGN §"Plan B", the downstream pipeline is unchanged.
- **No tests in MVP.** This is a personal tool; manual smoke tests per Phase 8 are the verification bar. Revisit if the codebase grows past ~1000 lines.
