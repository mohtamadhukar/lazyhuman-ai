# lazyhuman-ai

Claude Code plugin that turns an iOS Share-Sheet Shortcut into a structured Markdown workspace, with optional push to Apple Notes.

## How it works

1. iOS Shortcut packages what you share (URL, screenshot, text, PDF, audio) plus a tiny JSON meta block and emails it to `you+lh@gmail.com`.
2. A Gmail filter labels every such email `lazyhuman/inbox`.
3. Running `/process-inbox` in Claude Code:
   - drains the label into a local staging folder,
   - lets Claude extract/categorize each capture into your local workspace,
   - moves the Gmail message to `lazyhuman/processed`,
   - pushes touched files to Apple Notes (where configured).

## Install

1. **Gmail** — follow `docs/gmail-setup.md`: enable 2-Step Verification, create an app password, enable IMAP, create labels `lazyhuman/inbox` and `lazyhuman/processed`, set the filter.
2. **Deps** — `pip install -r requirements.txt`.
3. **Config** — `cp config.example.json config.json` and edit for your paths + Gmail address.
4. **Secret** — `cp .env.example .env` and paste the 16-char app password as `GMAIL_APP_PASSWORD`.
5. **iOS Shortcut** — follow `docs/ios-shortcut-setup.md` to build the Shortcut.

## Daily use

- Capture from anywhere on iOS via Share Sheet → Shortcut.
- At your desk, run `/process-inbox` in Claude Code.
- Optionally run `/sync-outputs` to force a full resync to Apple Notes.

## Layout

```
.claude-plugin/plugin.json     plugin manifest
commands/                      slash-command prompts
scripts/                       drain, file, sync, digest
scripts/_lib/                  config, Gmail client, frontmatter, sync adapters
skills/youtube-fetch/          vendored from agentic-systems
skills/pdf-to-markdown/        vendored from agentic-systems
templates/workspace-CLAUDE.md  starter workspace header
docs/                          setup guides
```
