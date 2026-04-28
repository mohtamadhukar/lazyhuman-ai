---
description: Drain the lazyhuman/inbox Gmail label, extract and file each capture into the workspace, then push touched files to sync targets.
---

# /process-inbox

Run the capture pipeline end-to-end in a single pass. All triage happens inline
in this same conversation; there is **no** cross-run review queue. A capture
either lands in the workspace (Gmail label flips to `processed`) or stays in
`lazyhuman/inbox` and re-surfaces next run.

Throughout: your workspace `CLAUDE.md` is auto-loaded by the Claude Code
harness. Use it for Identity, Dietary, People, Category conventions, New-file
policy, and Sync defaults.

## Phase 1 — Drain

Run:

```bash
python3 -m scripts.drain_gmail
```

Parse the JSON array on stdout. Each entry has shape:

```
{"id": "...", "folder": "<local_inbox_dir>/<day>/<id>", "kind": "...", "source_url": "...", "hint": "..."}
```

If the array is empty, print "no new captures" and stop. Don't run later phases.

Initialize an in-memory `last_run` object:

```
{
  "started_at": <ISO now>,
  "items": [],
  "sync": {},
  "finished_at": null
}
```

## Phase 2 — Process each capture

For each entry in the drain manifest:

1. **Read the staged files.** Read `<folder>/meta.json`. If a `payload*` file
   exists, Read it directly (for text / image / PDF) — the Read tool handles
   images natively. If `kind == "url"` and `source_url` is set, don't Read the
   staged folder's attachments (drain has already filtered junk); use WebFetch
   on the URL instead.

2. **Route by `kind`:**

   | kind                     | handler                                                                 |
   |--------------------------|-------------------------------------------------------------------------|
   | `url` + youtube domain   | `python3 skills/youtube-fetch/scripts/fetch.py "<url>"` (Bash, JSON out)     |
   | `url` + instagram domain | `python3 skills/instagram-fetch/scripts/fetch.py "<url>"` (Bash, JSON out)  |
   | `url` + tiktok domain    | add to inline triage: "re-capture as screenshot"                            |
   | `url` (other)            | `WebFetch` the URL with an extraction prompt                                |
   | `pdf`                    | `python3 skills/pdf-to-markdown/scripts/convert.py "<payload>"` (Bash)  |
   | `image` / `screenshot`   | Read the image path directly                                            |
   | `text`                   | use the body verbatim                                                   |
   | `audio`                  | add to inline triage: "audio transcription Post-MVP"                    |
   | `unknown`                | add to inline triage with a short reason                                |

3. **Decide the target file(s)** using workspace `CLAUDE.md` conventions. Prefer
   existing files. Create new files/folders freely when nothing fits (mention
   new files in the digest so the user can codify patterns later).

4. **Format and write content.**

   - Place entries (restaurants, shops, landmarks): format each as
     `- [<name>](https://maps.app.goo.gl/?q=<url-encoded name>) — <notes>`.
   - Tasks: `- [ ] <task>`.
   - Freeform notes: plain markdown under the relevant heading.
   - **YouTube captures MUST produce a per-video file containing (a) a
     header with title/channel/URL/duration, (b) a short "Key takeaways"
     section, and (c) the full transcript embedded inline as timestamped
     paragraph chunks of ~30 seconds each. Never discard the transcript.
     Before choosing the parent folder, confirm the categorization with
     the user (e.g. "liked & already watched" vs "watch later").**
   - **Instagram captures MUST produce a per-video file containing (a) a
     header with author handle / caption first line / URL / duration, (b)
     the full caption verbatim under a "Caption" subhead, (c) a short
     "Key takeaways" section, and (d) the full transcript embedded inline
     as timestamped paragraph chunks of ~30 seconds each. Image-only
     carousel posts (where `instagram-fetch` returns `error: "no video
     track"`) file the caption only and skip the transcript section.
     Confirm the parent folder with the user before writing (e.g.
     recipes vs travel vs fashion).**

5. **Append the visible source line** directly below the inserted section, as
   italic markdown:

   ```
   _Source: [<id>](https://mail.google.com/mail/u/0/#search/subject%3A%22%5BLH%5D+<id>%22) · captured <YYYY-MM-DD>_
   ```

   The `<YYYY-MM-DD>` is the `captured_at` date from `meta.json`. The link
   opens Gmail to the exact source email via the `[LH] <id>` subject search.
   The plain `<id>` must appear in the link text so `grep -r <id> <workspace>`
   can locate the capture later.

6. **Sync frontmatter on new files.** If this is a new file, walk the "Sync
   defaults" patterns in workspace `CLAUDE.md`. If a pattern matches the new
   file's path, write the corresponding `sync:` block into the file's YAML
   frontmatter, e.g.:

   ```yaml
   ---
   sync:
     - apple-notes:
         folder: Trips
         note: Japan Packing
   ---
   ```

   If no pattern matches, leave frontmatter off and add this new file to the
   inline "sync confirmation" list (handled in Phase 3).

7. **Edit or Write the workspace file.** Use the Edit tool when the file exists
   (to preserve surrounding content); Write only for new files.

8. **Close the loop on this capture.** Run:

   ```bash
   python3 -m scripts.file_item --id <id> --filed-to <relative path(s)>
   ```

   Exit 0 → append to `last_run.items`:
   `{"id": "<id>", "disposition": "processed", "filed_to": ["<paths>"]}`.

   Non-zero exit or any other failure during steps 1–7 → do **not** call
   `file_item.py`. Append with
   `{"id": "<id>", "disposition": "failed", "reason": "<short>"}` and add to
   the inline triage list so the user can decide.

## Phase 3 — Inline triage (same conversation)

For each capture flagged in Phase 2 as ambiguous, failed, or needing
re-capture, print a short human summary and ask what to do. Accept free-text
replies:

- **"file under &lt;path&gt;, note X"** → Write/Edit the file with the visible
  Source line, then run `file_item.py --id <id> --filed-to <path>`. Record
  `{"disposition": "processed", "filed_to": ["<path>"]}`.
- **"drop"** → `file_item.py --id <id>` with no `--filed-to`. Gmail label flips
  to `processed`; no workspace file created. Record
  `{"disposition": "dropped"}`.
- **"skip"** → do **nothing**. Gmail label stays `lazyhuman/inbox`; the capture
  re-surfaces on the next `/process-inbox` run. Record
  `{"disposition": "skipped"}`.

Also walk any new files collected under "sync confirmation" (step 6 with no
matched sync default). For each, ask something like
"`<file>` has no sync default — sync to Apple Notes (folder, note name), or
leave unsynced?" Write the frontmatter if confirmed.

## Phase 4 — Sync push

Collect every workspace file you touched (created or edited) across phases 2
and 3 into a space-separated list. Then:

```bash
python3 -m scripts.sync_push --touched-files <paths...>
```

Parse the JSON summary on stdout and write it into `last_run.sync`.

If no files were touched, skip this phase (and record `last_run.sync = {}`).

## Phase 5 — Write state + digest

Set `last_run.finished_at = <ISO now>`. Write `last_run` as pretty JSON to:

```
<local_inbox_dir>/.last-run.json
```

(`local_inbox_dir` is the same value `drain_gmail.py` used; it's in
`config.json` at the plugin root.)

Then run:

```bash
python3 -m scripts.digest
```

Show the digest output to the user.

## Failure modes to handle gracefully

- **Subprocess error** (youtube-fetch, pdf-to-markdown): add to triage list
  with the stderr tail; don't call `file_item.py`.
- **Unknown sync target** in a file's frontmatter: `sync_push.py` emits an
  error entry — surface it in the digest but keep going.
- **IMAP auth failure** during `file_item.py`: tell the user to check `.env`
  and regenerate the app password; don't retry automatically.
