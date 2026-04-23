# Technical Design: lazyhuman-ai

_Personal thought/link/media inbox processor. Lazy human captures, AI organizes._

## Context

### Requirements Reference

[2026-04-23-REQUIREMENTS-lazyhuman-ai.md](./2026-04-23-REQUIREMENTS-lazyhuman-ai.md)

### Codebase Analysis

Greenfield. The repo currently contains only `docs/plans/`. Two external dependencies shape the design:

- **Claude Code plugin ecosystem.** The user already ships plugins (e.g. `outlook-reader`, `lazy-pl-toolkit`) with the standard layout: `.claude-plugin/plugin.json`, `commands/`, `skills/`, `scripts/`. We match that.
- **Colleague skills at `~/LocalDocuments/Github/agentic-systems/skills/`.** Two skills are directly needed — `youtube-fetch` (transcript + metadata) and `pdf-to-markdown`. Per a late decision (see "Requirements Deltas"), these are **vendored** into `skills/` inside the plugin rather than referenced by absolute path, so the plugin is self-contained.

No prior art in this repo to match patterns against. All conventions chosen fresh.

### Requirements Deltas (must update REQUIREMENTS.md)

The design process surfaced four changes from the requirements as written:

1. **Transport is Gmail, not iCloud Drive.** The user's corp-managed Mac blocks iCloud Drive (and Dropbox / Google Drive). Gmail is universally allowed, gives us IMAP + the Gmail API, MIME attachment handling, labels as a built-in state machine, and a permanent audit trail. Supersedes the iCloud Drive references in REQ-001/002/007 and throughout.
2. **Colleague skills are vendored, not referenced.** User wants the plugin to be self-contained and not depend on a sibling repo. Supersedes REQ-008c's "don't copy their code" guidance.
3. **Update detection moves to Post-MVP.** Every capture is filed as a new entry for MVP; update semantics (`- [ ] milk` → `- [x] milk` on "bought milk") are deferred. Supersedes REQ-013, REQ-014, and simplifies REQ-015.
4. **Narrow output sync layer added to MVP (push only, Notes + Maps links).** Workspace Markdown is the source of truth but fans out to two consumer surfaces so captures become actionable: **Apple Notes** (push only, creates/replaces a named note per file) and **Google Maps clickable links** (local renderer, no API). **Reverses the "Markdown with clickable links only" line in the original Out-of-Scope list only for Apple Notes.** Apple Reminders round-trip and Google Sheets are demoted to Post-MVP (REQ-028, REQ-029). Adds MVP requirements REQ-026, REQ-027, REQ-030.

5. **REQ-019 (recipe → grocery cross-file append) demoted to Post-MVP.** Implementation requires narrow fuzzy-matching against existing grocery lines; coupled to update detection which is also deferred. Moves alongside REQ-013/014.

Plan B (Apple Notes as transport) is documented below in case Gmail proves unworkable. Note this is independent of Apple Notes as a sync target — same app, different folders.

### New requirements (to insert into REQUIREMENTS.md)

- **REQ-026: Output sync layer (MVP scope: push only, Apple Notes + Google Maps links).** After filing, the processor pushes touched workspace files to declared sync targets. Sync runs at end of `/process-inbox`. No pull, no shared state, no conflict handling in MVP.
- **REQ-027: Sync target declaration.** Each workspace file can declare sync targets in YAML frontmatter (`sync:` block). `CLAUDE.md` has a "Sync defaults" section carrying pattern-based defaults (e.g., `trips/*/vegan-spots.md → apple-notes + google-maps-links`). When Claude creates a new file, it consults pattern defaults and writes matching sync config into the file's frontmatter; if no pattern matches, it asks in the review phase.
- **REQ-030: Sync outcome reporting.** End-of-run digest reports per-target: N pushed, N errors. Sync failures are non-fatal (capture processing succeeded; retry next run).
- **REQ-028 (Post-MVP): Apple Reminders sync with shared round-trip.** Deferred.
- **REQ-029 (Post-MVP): Google Sheets sync.** Deferred.

## Architecture

### Component Diagram

```
 iPhone                                  Gmail                         Mac (corp, Claude Code plugin)
 ━━━━━━                                  ━━━━━                         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                                                        ┌──────────────────────────┐
  ┌──────────────────┐      Send Email    ┌──────────┐   IMAP +         │  /process-inbox command  │
  │ Share Sheet /    │──────────────────▶ │ Inbox    │   Gmail API      │  ─────────────────────── │
  │ home-screen icon │   (attachments,    │ label:   │ ◀──────────────▶ │  1. drain_gmail.py       │
  │                  │    JSON meta body) │ lazyhuma │                  │  2. Claude reasons over  │
  │ "lazyhuman-ai"   │                    │ n/inbox  │                  │     each capture:        │
  │ Apple Shortcut   │                    │          │                  │     - extract (vision,   │
  └──────────────────┘                    └──────────┘                  │       WebFetch, skills)  │
                                                                         │     - categorize         │
                                                                         │     - render output MD   │
                                                                         │     - file to workspace  │
                                                                         │  3. update Gmail label   │
                                                                         │  4. review phase         │
                                                                         │  5. digest              │
                                                                         └──────────────────────────┘
                                                                                   │
                                                                                   ▼
                                                                         ┌──────────────────────────┐
                                                                         │  local workspace (MD)    │
                                                                         │  ~/LocalDocuments/       │
                                                                         │    lazyhuman-workspace/  │
                                                                         │  ─────────────────────── │
                                                                         │  trips/japan/...         │
                                                                         │  reading.md              │
                                                                         │  grocery.md              │
                                                                         │  recipes/                │
                                                                         │  ideas.md                │
                                                                         │  (visible Source line  │
                                                                         │   inline in each file) │
                                                                         └──────────────────────────┘
```

### Two-Layer Split

- **Capture layer (iOS):** one Apple Shortcut, invoked from Share Sheet or home-screen icon, that sends a structured email to a dedicated Gmail plus-address. Zero local categorization; all captures land in a single Gmail label.
- **Processor layer (Mac, Claude Code plugin):** the `/process-inbox` slash command orchestrates a run. Python helpers do deterministic work (drain Gmail → local inbox, close capture, digest). Claude does the semantic work (extract, categorize, pick output shape, write Markdown). The staging folder is ephemeral — deleted on filing. No local archive is kept; Gmail is the authoritative store. Auto-run on a schedule is Post-MVP.
- **Sync layer (Mac, Python):** after filing, `scripts/sync_push.py` pushes touched files to their declared sync targets (Apple Notes, Google Maps links). Push-only in MVP; no pull, no shared-state reconciliation. Deterministic, driven entirely by per-file frontmatter + `CLAUDE.md` defaults — no Claude judgment at sync time.

### Components

#### 1. iOS Capture Shortcut

- **Responsibility:** accept shared content or free input from the user; package it as an email; send to Gmail plus-address.
- **Interface:**
  - **Inputs:** Share Sheet payload (URL / image / screenshot / PDF / selected text) OR home-screen tap (menu: paste link / pick image / dictate / type).
  - **After payload acquired:** show one prompt for optional free-text or dictated processing hint.
  - **Output:** email to `<user>+lh@gmail.com` with:
    - Subject: `[LH] <id>` where id = `YYYYMMDD-HHMMSS-<4hex>` (derived from `Current Date` + `Random Number`).
    - Body: a JSON block (built via Shortcuts `Dictionary` → `Get Dictionary as JSON` actions) carrying meta.
    - Attachments: any image / screenshot / PDF / audio from the share payload.
- **Dependencies:** personal Gmail account configured in iOS Mail.app (the Shortcut uses the native `Send Email` action, sending headlessly with `Show When Run: Off`). No API keys on device.

#### 2. Gmail Label State Machine

- **Responsibility:** queue + state tracking for captures in flight.
- **Setup (one-time):** a Gmail filter matches `to:<user>+lh@gmail.com` and applies label `lazyhuman/inbox`. Skips the Inbox, so captures don't clutter the user's primary mail.
- **MVP states (only two — Gmail is the authoritative queue):**
  - `lazyhuman/inbox` — pending, not yet processed (or deferred; re-surfaces next run)
  - `lazyhuman/processed` — filed successfully (or explicitly dropped by the user)
- **Ambiguous / failed captures do NOT get a separate label.** They stay in `lazyhuman/inbox`; single-pass inline triage at the end of a `/process-inbox` run resolves them (file / drop / skip). Skipped captures re-appear on the next run.
- **"Where did this capture end up?" is answered by a visible source line inside the workspace file** — Claude appends `_Source: [<capture_id>](<gmail-deep-link>) · captured <YYYY-MM-DD>_` next to content it writes. The capture_id appears in plain text so `grep -r <id> <workspace>` locates it; the link opens Gmail filtered to the original email. No separate ledger file.

#### 3. `/process-inbox` Slash Command

- **Responsibility:** single entry point for a processing run. Lives at `commands/process-inbox.md`. The command prompt tells Claude the run sequence and provides the tools.
- **Phases:**
  1. **Drain** — call `scripts/drain_gmail.py`, which fetches all `lazyhuman/inbox` messages, writes each as a local capture folder, and returns a JSON manifest of pending items.
  2. **Process** — iterate each item. Claude reads payload (text / image / PDF via Read; URL via WebFetch; YouTube via vendored `skills/youtube-fetch/`; PDF via vendored `skills/pdf-to-markdown/`). The workspace-root `CLAUDE.md` is already in context (auto-loaded by the Claude Code harness — no explicit read step). For each item: decide category target + output shape (task / list-entry / note), produce Markdown, Edit/Write to workspace. When creating a new file, consult `CLAUDE.md` sync-defaults and write matching `sync:` frontmatter into the file.
  3. **Finalize per item** — call `scripts/file_item.py` to delete the staging folder and flip the Gmail label (`inbox` → `processed`).
  4. **Triage phase (inline, same conversation)** — for each capture Claude flagged as ambiguous during Process, present a short summary and accept a free-text reply: *file under X* / *drop* / *skip*. Resolved items go through Finalize; skipped items leave the Gmail label untouched so they re-surface on the next run. Also covers sync-target confirmation for new files where no default rule matched.
  5. **Sync push** — call `scripts/sync_push.py --touched-files <list>` to push workspace changes to declared targets (Apple Notes). Maps links are already embedded inline by Claude during Process; no post-process step.
  6. **Digest** — call `scripts/digest.py` to print an end-of-run summary, including sync outcomes per target.
- **Dependencies:** everything below.

#### 4. `scripts/drain_gmail.py`

- **Responsibility:** Gmail → local inbox.
- **Interface:**
  - **Input:** none (reads config.json for Gmail address + label names; reads refresh token from macOS Keychain).
  - **Output (stdout):** JSON manifest of captures written.
  - **Side effects:** creates one folder per capture under `<local_inbox_dir>/YYYY-MM-DD/<id>/` containing `meta.json` + any extracted `payload.*`; does NOT change Gmail labels (label transitions happen per-item in `file_item.py` after Claude has filed successfully — drain is non-destructive). No `.eml` snapshot is kept — Gmail is the source of truth, and `gm_msgid` in `meta.json` is the re-fetch handle.
- **Implementation:** `imapclient` + Gmail IMAP (app password from `.env`). Select `lazyhuman/inbox`, fetch RFC822 + X-GM-MSGID, parse with stdlib `email`, extract JSON meta block from body.

#### 5. `scripts/file_item.py`

- **Responsibility:** close a single capture — delete the staging folder and flip the Gmail label.
- **Interface:**
  - **Input:** `--id <capture-id>` (required), `--filed-to <path>...` (optional, currently unused; reserved for future logging), `--day YYYY-MM-DD` (optional fast-path).
  - **Side effects:** reads `gm_msgid` from `meta.json`; `shutil.rmtree` the staging folder; IMAP-MOVE the message from `lazyhuman/inbox` to `lazyhuman/processed`. No archive is kept. Ambiguous / skipped captures do NOT call `file_item.py` — they stay in `lazyhuman/inbox` and re-surface on the next drain.

#### 6. `scripts/digest.py`

- **Responsibility:** end-of-run human-readable summary.
- **Interface:**
  - **Input:** run id or "last run" (reads state from `<local_inbox_dir>/.last-run.json`).
  - **Output (stdout):** short summary: `N filed, N flagged for review, N failed`, with `_review.md` path if non-empty. Sync block per target: `apple-reminders: 3 pushed, 2 pulled (1 new from priya, 1 completed)`.

#### 6a. `scripts/sync_push.py`

- **Responsibility:** push workspace files to their declared sync targets.
- **Interface:**
  - **Input:** `--touched-files <path> [<path> ...]` (from processor); or `--all` for full resync.
  - **Per-file behavior:** parse frontmatter, dispatch to per-target adapters. Each adapter is idempotent (safe to re-push).
  - **Output (stdout):** JSON per-file-per-target result (ok / skipped / error with reason).
- **Target adapters (MVP):**
  - `apple_notes`: AppleScript via `osascript`. Creates or updates a named note in a folder with the rendered markdown (Notes supports rich text — render checkboxes for task-shape files). Replaces body on each push (no diff state needed).
- **Maps links are NOT a sync adapter.** Each place entry is rendered inline as a Markdown link: `- [<place name>](https://maps.app.goo.gl/?q=<urlencoded-name>) — <notes>`. Claude does this as part of extraction; no companion file, no adapter, no post-process step.
- **Deferred adapters (Post-MVP):** `apple_reminders` (REQ-028), `google_sheets` (REQ-029).

#### 6b. `/sync-outputs` slash command (standalone)

- Thin wrapper that calls `sync_push.py --all`. Useful for backfill and one-shot resync after editing `CLAUDE.md` sync defaults.

#### 7. Workspace-root `CLAUDE.md`

- **Responsibility:** user-editable standing facts that shape Claude's extraction and categorization decisions. Lives at `<workspace_dir>/CLAUDE.md`. Auto-loaded by the Claude Code harness on every run — no explicit read step in `/process-inbox`.
- **Note:** this replaces the earlier `preferences.md` concept. Same role, different filename; leverages Claude Code's native project-memory loading.
- **Structure:** one H2 per section.
  ```markdown
  ## Identity
  - Name: Madhukar. Timezone: PT.

  ## Dietary
  - Vegan (strict), no mushrooms, ...

  ## People
  - Priya: wife, vegan, PT.
  - (add others as they come up in captures)

  ## Category conventions
  _(empty to start — fills in as patterns emerge. Example lines to seed once a pattern repeats:)_
  _- reading.md — articles/essays; 3-bullet summary + link_
  _- trips/<name>/vegan-spots.md — each entry a markdown link with embedded Google Maps URL_

  ## New-file policy
  - Create new files/folders freely when no existing file fits. Report new files in the digest so the user can notice emerging patterns and (optionally) codify them here later.

  ## Sync defaults (MVP: apple-notes only)
  _(empty to start; add pattern rules as sync needs emerge, e.g.:)_
  _- trips/*/packing.md → apple-notes {folder: "Trips", note: "<trip-name> Packing"}_
  _- reading.md → apple-notes {folder: "Reading", note: "Reading List"}_
  ```
- **Dependencies:** none.

#### 8. Vendored Skills (`skills/youtube-fetch/`, `skills/pdf-to-markdown/`)

- **Responsibility:** type-specific extractors pulled in from `agentic-systems`.
- **Interface:** unchanged from upstream — both are invoked as subprocesses by Claude (via Bash tool) and return JSON:
  - `python skills/youtube-fetch/scripts/fetch.py "<url>"`
  - `python skills/pdf-to-markdown/scripts/convert.py "<path>"`
- **Why vendored:** self-contained plugin, not dependent on a sibling repo's state; updates pulled manually as needed.
- **Dependencies:** `youtube-transcript-api`, `yt-dlp`, `pymupdf4llm` (Python packages listed in the plugin README's install instructions).

#### 9. Config (`config.json`) + Secrets (macOS Keychain)

- **`config.json`** (gitignored; `config.example.json` shipped):
  ```json
  {
    "workspace_dir": "~/LocalDocuments/lazyhuman-workspace",
    "local_inbox_dir": "~/LocalDocuments/lazyhuman-inbox",
    "gmail_address": "mohtamadhukar+lh@gmail.com",
    "labels": {
      "inbox": "lazyhuman/inbox",
      "processed": "lazyhuman/processed"
    }
  }
  ```
- **Keychain (via Python `keyring`):**
  - service: `lazyhuman-ai`
  - account: `gmail-oauth`
  - password: JSON with `{refresh_token, client_id, client_secret}`.
- **Install flow:** `cp config.example.json config.json`, edit paths, run `python scripts/setup_gmail_auth.py` to complete OAuth device-code flow and write to Keychain.

## Data Models

### Capture (email in Gmail)

```
Subject: [LH] 20260423-143021-a7f3
To: mohtamadhukar+lh@gmail.com
Body (text/plain):
  ```json
  {
    "id": "20260423-143021-a7f3",
    "captured_at": "2026-04-23T14:30:21-07:00",
    "captured_by": "madhukar",
    "kind": "screenshot",
    "source_app": "Instagram",
    "source_url": "https://...",
    "hint": "add to Japan trip"
  }
  ```
  <optional free-text payload below the JSON block>
Attachments: screenshot.png (and/or payload.pdf, payload.m4a, etc.)
Label: lazyhuman/inbox
```

- `kind` ∈ `url | text | image | screenshot | pdf | audio`. Set by the Shortcut based on share payload type.
- `captured_by` is a hardcoded string set inside the Shortcut at install time on each phone (e.g. `"madhukar"` on his iPhone, `"priya"` on wife's iPhone). Single Gmail inbox, but the processor can attribute each capture to its author and apply person-specific preferences.
- `source_app` is best-effort from `Shortcut Input` metadata (Instagram, Safari, Photos, etc.); may be empty.
- `source_url` present when the capture is or includes a URL.
- `hint` present when the user answered the hint prompt.

### Capture (local, post-drain)

```
<local_inbox_dir>/
  2026-04-23/
    143021-a7f3/
      meta.json
      payload.png          # from email attachment
      payload.txt          # optional, from email body below JSON block
      email_snapshot.eml   # full original MIME for forensic re-processing
```

### `meta.json` schema

```json
{
  "id": "20260423-143021-a7f3",
  "captured_at": "2026-04-23T14:30:21-07:00",
  "captured_by": "madhukar",
  "kind": "screenshot",
  "source_app": "Instagram",
  "source_url": "https://...",
  "hint": "add to Japan trip",
  "gmail_message_id": "18f4a9c2b3d5e7f1",
  "status": "pending",
  "processed_at": null,
  "disposition": null,
  "filed_to": []
}
```

- `meta.json` lives only during a processing run; it is deleted when `file_item.py` runs. Only `id`, `captured_at`, `captured_by`, `kind`, `source_url`, `hint`, `gm_msgid`, and `attachments` are persisted — no `status`, `disposition`, `processed_at`, or `filed_to` (those were archive-era bookkeeping, now gone).
- Post-filing, the authoritative "what happened to this capture?" is the Gmail label (`lazyhuman/processed`) plus the workspace breadcrumb (`grep -r <id> <workspace>`).

### Workspace output (per REQ-017) — **illustrative only; the tree grows organically**

```
<workspace_dir>/
  CLAUDE.md                       # workspace-root standing facts; auto-loaded by Claude Code on every run
  # Everything below is emergent. Claude creates files/folders as captures dictate,
  # and appends a visible source line (italic markdown with a Gmail deep-link)
  # next to each insertion so readers can click back to the originating email
  # and `grep -r <id> <workspace>` can answer "where did this capture end up?".
  # Example shapes that might appear after a week of use:
  #   reading.md
  #   grocery.md
  #   ideas.md
  #   recipes/<slug>.md
  #   trips/japan/{tasks,packing,vegan-spots,notes}.md
  #   people/<name>.md
```

MVP has no `_sync-state/` directory: Apple Notes push replaces the note body each run (no diff needed). Sync-state storage returns when Reminders / Sheets land Post-MVP.

### Workspace file frontmatter (sync declaration)

```yaml
---
sync:
  - apple-notes:
      folder: "Trips"
      note: "Japan Packing"
---
- [ ] Pasmo card
- [ ] Ryokan confirmation printout
```

Frontmatter is optional. Files without a `sync:` block are local-only. The processor writes frontmatter on new files based on `CLAUDE.md` sync-default rules.

MVP has no sync-state file: Apple Notes push is full-body replace, and Google Maps links are regenerated from source each run.

## Interfaces

### 1. iOS → Gmail (capture)

**Trigger:** Share Sheet on iPhone, or home-screen Shortcut tap.

**Shortcut body (high-level):**

```
# One-time config action at the top of the Shortcut, edited per install:
CAPTURED_BY = "madhukar"   # ← set to "priya" on wife's phone

if home-screen invocation:
  menu: [paste link, pick image, dictate, type]
  → sets PAYLOAD variable
else (Share Sheet):
  PAYLOAD = Shortcut Input
ask "optional hint" (text, dictatable) → HINT
id = format-date(now, "yyyyMMdd-HHmmss") + "-" + lower(hex(random(0, 65535), 4))
meta = dictionary {
  id, captured_at: ISO-8601(now), captured_by: CAPTURED_BY,
  kind: infer(PAYLOAD),
  source_app: PAYLOAD.app, source_url: extract-url(PAYLOAD),
  hint: HINT
}
body = "```json\n" + json(meta) + "\n```\n" + text-part(PAYLOAD, "")
Send Email:
  to: mohtamadhukar+lh@gmail.com
  subject: "[LH] " + id
  body: body
  attachments: binary-parts(PAYLOAD)
  show when run: Off
```

**Contract:** at-most-once (Shortcut retries via queued send if offline). Email body must contain a fenced ```json ... ``` block as the first non-empty content.

### 2. Gmail → Drain script (IMAP/Gmail API)

**Trigger:** `scripts/drain_gmail.py`, invoked by `/process-inbox`.

**Query:** `users().messages().list(userId='me', q='label:lazyhuman/inbox')`.

**For each message:** `users().messages().get(id=msg_id, format='full')`:

1. Parse MIME parts; extract JSON block from first `text/plain` part → meta.
2. Walk attachments; write each to `<local_inbox_dir>/<day>/<id>/payload.<ext>`. Multiple attachments are suffixed (`payload-0.png`, `payload-1.png`) only if more than one binary part.
3. Write `email_snapshot.eml` (raw original).
4. Write `meta.json` (augmented with `gmail_message_id`, `status: "pending"`).
5. **Do not change label** — that's `file_item.py`'s job after Claude has filed.

**Output (stdout):** JSON array of captures, one object per item, with `id`, local folder path, `kind`, `source_url`, `hint`.

### 3. Per-item processing (Claude orchestration inside the slash command)

For each item in the drain manifest, the `/process-inbox` command prompt instructs Claude to:

| If `kind` is... | Extraction path |
|---|---|
| `url` (generic) | WebFetch the URL; extract title, description, 3-bullet summary for articles, or structured fields for Yelp/TripAdvisor/Maps/Tweets. |
| `url` (YouTube) | Shell-out to `python skills/youtube-fetch/scripts/fetch.py <url>`; use metadata + transcript. |
| `url` (Instagram/TikTok) | WebFetch will mostly fail. Write the URL to `_review.md` with "re-capture as screenshot" note. Update the digest flag. |
| `image` / `screenshot` | Read the image directly (Claude's vision). OCR overlay text, interpret scene, extract entities (places / items / recipes). |
| `pdf` | Shell-out to `python skills/pdf-to-markdown/scripts/convert.py <path>`; read the resulting .md. |
| `text` | Use the body text directly. |
| `audio` | Not supported in MVP; write to `_review.md` as "audio transcription pending (Post-MVP)". |

Then:

1. `CLAUDE.md` is already in context (harness auto-load). Refer to it for identity / dietary / people / sync-defaults.
2. Decide target file(s) and output shape (`- [ ]` task, bullet list entry, paragraph note). For any place entry, format inline as `- [<place name>](https://maps.app.goo.gl/?q=<urlencoded-name>) — <notes>` (rule carried in the command prompt itself, not `CLAUDE.md`).
3. Edit/Write the workspace file. For a recipe capture, also Edit `grocery.md` to append any missing ingredients.
4. Call `scripts/file_item.py --id <id> --disposition processed --filed-to <paths>`.

### 4. Review phase (conversational)

At end of run, Claude reads `_review.md`. For each unresolved entry, it shows the user the extracted content + its best-guess targets, then accepts a natural-language reply:

- `"trips/japan/vegan-spots, and add it's a ramen place"` → re-file with that hint.
- `"drop"` → remove from `_review.md`, update Gmail label.
- `"skip"` → leave for next run.
- `"add a new category: home/kitchen, file it there, and note the convention"` → propose a `CLAUDE.md` patch for user approval.

Review resolutions call `scripts/file_item.py` with the appropriate disposition.

### 5. Subprocess contracts (vendored skills)

Both vendored skills use subprocess-call + JSON-stdout. Claude reads the JSON, handles errors (e.g. `NoTextContent` for scanned PDFs, transcript unavailable for YouTube) by writing the item to `_review.md` with the specific failure reason.

### 6. Sync adapters (outbound)

Each sync target adapter is a module under `scripts/_lib/sync_adapters/`:

- `apple_notes.py` — AppleScript via `osascript`. Works against `tell application "Notes"`. Creates note with a deterministic title, replaces body on each push.

Post-MVP adapters (`apple_reminders.py`, `google_sheets.py`) slot into the same pattern when REQ-028 / REQ-029 land.

Maps links are not an adapter — Claude embeds them inline during extraction, directly in the source file.

Adapters expose a uniform interface (push-only in MVP):

```python
class SyncAdapter:
    def push(self, file_path: str, config: dict) -> dict:
        """Returns summary {pushed, skipped, errors}."""
```

### 7. Gmail API scopes (OAuth)

Stored refresh token grants:
- `https://www.googleapis.com/auth/gmail.modify` — read messages, apply/remove labels

Sheets/Drive scopes are Post-MVP (REQ-029). Single Google OAuth client; extra scopes added when that lands.

## Technical Decisions

| # | Decision | Choice | Rationale | Alternatives Considered |
|---|---|---|---|---|
| 1 | Plugin shape | Claude Code plugin: `commands/process-inbox.md` + Python helpers in `scripts/` + vendored skills in `skills/` | Matches user's existing plugins; Claude handles semantic work, Python handles deterministic I/O | Standalone Python CLI (loses Claude reasoning); menu-bar Mac app (heavy) |
| 2 | Capture transport | **Gmail** with MVP two-label state machine (`lazyhuman/inbox` → `lazyhuman/processed`) | Corp Mac blocks iCloud Drive / Dropbox / Google Drive; IMAP is universally allowed; MIME attachments are a solved problem; labels are a free state machine; permanent audit trail | iCloud Drive (per original REQ, blocked); Apple Notes (Plan B, slower AppleScript); SharePoint (heavier); email via work Outlook (pollutes work inbox); Syncthing/Tailscale (IT likely to block) |
| 3 | Inbox layout (local, post-drain) | **Ephemeral staging only**: `<day>/<id>/{meta.json, payload.*}` during a run; deleted by `file_item.py` on filing. No `.eml` snapshot, no `_archive/`. Gmail is the authoritative store; `gm_msgid` in meta.json is the re-fetch handle. | Keeps only one byte-copy of payloads (Gmail's); trivial disk footprint; re-processing a filed capture = one Gmail label flip + re-drain | Keep `_archive/` + `.eml` snapshot forever (earlier design); flat timestamped files |
| 4 | Meta format | JSON block in email body → `meta.json` sidecar on disk | Shortcuts `Dictionary → Get Dictionary as JSON` emits it natively; Python reads in one line; typed | YAML frontmatter (Shortcut string-builds fragile); key=value (no typing) |
| 5 | Standing-facts store | Single workspace-root `CLAUDE.md` with H2 sections, auto-loaded by Claude Code harness | Zero explicit-read step; leverages native project-memory loading; fits in one context load; split only needed past ~200 lines | Bespoke `preferences.md` requiring explicit read (earlier design); split across multiple files (over-engineered) |
| 6 | Update detection | **Deferred to Post-MVP** — every capture filed as new | Requires requirements update (REQ-013/014 → Post-MVP); simplifies MVP dramatically; adoption & capture quality matter more for v0 than update magic | Target-scoped fuzzy + Claude verdict; pure-Claude reasoning over full file; embeddings index |
| 7 | Ambiguous filing | **Single-pass inline triage** at the end of `/process-inbox`. Claude presents each ambiguous capture in-chat; user answers *file under X* / *drop* / *skip*. Skipped captures stay in `lazyhuman/inbox` and re-surface next run. No local review file, no extra Gmail label. | One conversation, one pass; zero cross-run state; Gmail is the authoritative re-queue | Dedicated `lazyhuman/review` label + `_review.md` queue (earlier design — rejected as more state than needed); batch triage via separate command |
| 8 | Config & secrets | `config.json` (gitignored, paths + labels) + `.env` with `GMAIL_APP_PASSWORD` (gitignored) + `config.example.json` / `.env.example` as install templates | Separates diffable config from secrets; app password flow is simpler than OAuth for a single user; one-line install | macOS Keychain via `keyring` (earlier design — rejected in favour of `.env` portability); all in config.json (secrets on disk alongside config) |
| 9 | Colleague skills integration | **Vendored** under `skills/youtube-fetch/` and `skills/pdf-to-markdown/` | Plugin is self-contained; not dependent on sibling repo's state; user owns updates. Supersedes REQ-008c's "don't copy" guidance | Subprocess-call via absolute path (per original REQ-008c); re-implement inline (duplicated work) |
| 10 | Vision / OCR | Claude Code's native image Read | No extra dependency; free; handles OCR + scene understanding in one call | Separate OCR tool (Tesseract); GPT-4V via API |
| 11 | Web fetching | `WebFetch` tool | Already in the Claude Code toolset; covers articles, Yelp, Maps, YouTube metadata; REQ-008a pre-identifies unreliable sources | Playwright (heavy, for Post-MVP if IG/TT screenshots insufficient) |
| 12 | Run invocation | Manual `/process-inbox` command | MVP per REQ-007; schedule/fswatch is Post-MVP REQ-020 | cron; launchd agent; fswatch on a non-existent inbox folder (N/A given Gmail transport) |
| 13 | Auto-run fit for Gmail transport | `fswatch` doesn't apply (Gmail is remote); Post-MVP auto-run = launchd timer calling `/process-inbox` every N minutes | Native, always-on, no extra daemons | cron (pre-launchd); Gmail push notifications via Pub/Sub (heavy setup) |
| 14 | Output sync — MVP targets | **Apple Notes (push only)** + **Google Maps clickable links (local renderer)** | Narrowest scope that proves the sync layer without committing to round-trip state management; Reminders / Sheets deferred to Post-MVP (REQ-028/029) | Fuller sync (Reminders round-trip, Sheets) was scoped down after scope-creep review |
| 15 | Sync trigger | Push at end of `/process-inbox` (touched files only). Standalone `/sync-outputs` for full resync | Push is incremental; standalone command for backfill after preferences changes. No pull phase in MVP. | Full scan every run (slow); separate commands only (extra step) |
| 16 | Sync declaration | Frontmatter per file + `CLAUDE.md` sync-defaults pattern rules | Per-file explicit, pattern rules for new-file auto-config, both coexist. Claude writes frontmatter at file creation based on matched defaults. | Preferences.md only (every new file requires pref edit); frontmatter only (no defaults, verbose) |
| 17 | Sync orchestration pattern | Pluggable adapters under `scripts/_lib/sync_adapters/`, uniform `push` interface | Each target is isolated; adding Reminders / Sheets / Todoist later = one new adapter file (and adding `pull` to the interface when Reminders lands) | Monolithic sync script (grows unwieldy); in-Claude sync (burns tokens unnecessarily) |

## Plan B: Apple Notes transport (documented fallback)

If Gmail proves unworkable (OAuth friction, spam misclassification, iOS Shortcut `Send Email` reliability issues, or the user simply prefers it), the transport can be swapped for Apple Notes with minimal impact on the rest of the design:

- **iOS capture:** Shortcut creates a new note in a `lazyhuman-inbox` Notes folder. Title = capture id. Body = JSON meta block + payload text. Image/PDF = note attachment.
- **Mac drain:** `scripts/drain_notes.py` replaces `drain_gmail.py`. Uses AppleScript via `osascript` to enumerate notes in the inbox folder, extract body + saved attachments (`save attachment X in POSIX file Y`), then moves the note to `lazyhuman-archive` folder.
- **State machine:** folder membership instead of labels. Ambiguous items stay in an intermediate `lazyhuman-review` folder.
- **Costs:** AppleScript-to-Notes is 1-2s per note (vs millisecond IMAP); attachment extraction is fiddlier; no cross-device audit log beyond Notes' own.
- **Everything downstream of drain is identical.** `file_item.py` becomes a thin wrapper around an AppleScript move instead of a Gmail label change.

The drain is the only swappable component. Keep the interface of `drain_*.py` consistent (reads config, writes folder-per-capture, returns JSON manifest on stdout) so substitution is a config toggle.

## File / Module Layout

```
lazyhuman-ai/
├── .claude-plugin/
│   └── plugin.json
├── .gitignore
├── README.md
├── commands/
│   ├── process-inbox.md                # the slash command prompt
│   └── sync-outputs.md                 # standalone full-resync command
├── config.example.json
├── templates/
│   └── workspace-CLAUDE.md             # starter CLAUDE.md copied into workspace on first init
├── scripts/
│   ├── drain_gmail.py
│   ├── file_item.py
│   ├── digest.py
│   ├── sync_push.py
│   └── _lib/
│       ├── config.py                   # reads config.json + .env
│       ├── gmail_client.py             # IMAP wrapper (imapclient)
│       ├── frontmatter.py              # parse/write YAML frontmatter
│       └── sync_adapters/
│           ├── __init__.py             # registry mapping target-name → adapter class
│           ├── apple_notes.py
│           └── google_maps_links.py
│           # apple_reminders.py, google_sheets.py → Post-MVP (REQ-028, REQ-029)
├── skills/
│   ├── youtube-fetch/                  # vendored
│   └── pdf-to-markdown/                # vendored
└── docs/
    ├── ios-shortcut-setup.md           # how to build the Shortcut
    ├── gmail-setup.md                  # filter + OAuth instructions
    └── plans/
        ├── 2026-04-23-REQUIREMENTS-lazyhuman-ai.md
        └── 2026-04-23-DESIGN-lazyhuman-ai.md
```

The **workspace directory** (output Markdown tree) lives _outside_ the plugin, at `~/LocalDocuments/lazyhuman-workspace/` per `config.json`, so the plugin repo doesn't bloat with personal content.

The **local inbox directory** is similarly external at `~/LocalDocuments/lazyhuman-inbox/` — an ephemeral staging area; folders are deleted by `file_item.py` on filing. Between runs, the directory only contains unresolved captures (skipped in the previous triage, pending the next drain).

## Starter Scope (REQ-018, updated)

Shipped:

- **Empty workspace.** No pre-seeded category files or folders. First captures create the first files.
- **Minimal `CLAUDE.md` skeleton** at the workspace root with Identity / Dietary / People populated. Sync-defaults and Category-conventions sections start empty and fill in as patterns emerge. Copied from `templates/workspace-CLAUDE.md` by the install / init step.
- No pipeline-managed side-files (`_review.md`, `_archive/`) are shipped or created. Ambiguous captures are resolved inline; "where did this capture end up?" is answered by the visible `_Source: [<id>](<gmail-link>) · captured <date>_` line Claude appends inside each workspace file it writes.

## Success-criteria mapping

| REQ success criterion | How the design supports it |
|---|---|
| ≥80% adoption after 2 weeks | Gmail transport removes capture friction; headless `Send Email` from Shortcut is 1-2 taps + optional hint; sync layer makes workspace output immediately useful (Reminders on phone, shared with wife) |
| ≥80% categorization accepted without edits | Workspace `CLAUDE.md` + the review phase provide a tight feedback loop; Claude gets full standing-facts context every run (harness auto-load) |
| Reel-screenshot → Maps-linked list in <60s | Vision OCR + pref-driven categorization; no external API round-trips on the hot path; Google Maps clickable-link generation is local-only |
| ≤3 taps / ≤10s capture latency | Share Sheet → Shortcut → send email (headless) is 2 taps + optional hint |
| Zero silent data loss | Gmail is the single authoritative store for every capture; `file_item.py` only flips the label after the workspace file exists; un-resolved triage items stay in `lazyhuman/inbox` and re-surface every run until handled; sync failures are retriable (workspace is canonical) |

## Open Questions

- **Gmail `Send Email` silence on iOS 17+.** The Shortcut's `Send Email` action with `Show When Run: Off` should send headlessly once an account is configured in Mail.app. If iOS surfaces a one-time privacy prompt, that's acceptable. If it prompts every time, we swap to the Gmail REST API via `Get Contents of URL` + stored OAuth bearer in the Shortcut. Need to confirm behavior after install.
- **Attachment size limits.** Gmail caps attachments at 25 MB; typical captures (screenshots, PDFs) are well under. Audio memos could push this if Post-MVP REQ-022 lands — cross that bridge later.
- **Multiple attachments per capture.** The Shortcut currently emits one email per invocation. A share with N images should attach all N; the drain suffixes filenames (`payload-0.png`, `payload-1.png`). Confirm Shortcut produces multiple-attachment emails correctly.
- **Gmail rate limits.** The Gmail API has per-user quotas (1B quota units/day, ~250/user/sec for reads). For personal use: not a concern. Flag if scaling beyond one user.
- **Duplicate captures.** The Shortcut's id includes timestamp + random hex, so same-second captures from two devices (iPad + iPhone) won't collide. Drain is idempotent via Gmail message id.
- **Archive growth.** Local archive is eliminated; only Gmail retains. Gmail retention is user's call (no automated purge from this tool).
- **Google Maps link file is read-only.** `*.maps.md` is a generated companion — if the user edits it, changes are clobbered on next sync. Stamp `<!-- generated, do not edit -->` at the top.
- **Apple Notes body replacement.** Push replaces the note body each run, so if the user or collaborator edits the Note directly, those edits are overwritten on next push. MVP accepts this (workspace Markdown is source of truth). Post-MVP can add diff-aware push.
- **(Deferred — Post-MVP with REQ-028/029):** shared-list invite flow, Reminders list naming collisions, pull text-matching fragility, wording reconciliation, delete semantics, Sheets target file shape.

## Workflow Gate

Technical design complete. Recommended next step: run `/write-plan` to convert this design into an actionable implementation plan, or `/grumpy` for an adversarial review of the technical decisions before committing to code.
