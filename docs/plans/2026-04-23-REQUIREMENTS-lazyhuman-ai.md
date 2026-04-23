# Requirements: lazyhuman-ai

_Personal thought/link/media inbox processor. Lazy human captures, AI organizes._

## Problem Statement

Throughout the day, the user generates and encounters many fragments worth keeping: stray thoughts, articles, tweets, Instagram reels, screenshots, voice memos, places seen, purchase ideas, recipes, things to follow up on. These fragments end up scattered across Apple Notes, Reminders, camera roll, browser bookmarks, and DMs to self — and mostly get lost.

Three compounding pains:

1. **Capture friction** — opening an app, picking a list, typing is too slow; by the time it's done, the thought is gone or the link is buried.
2. **No organization** — captures pile up in flat lists; grocery items mix with Japan trip notes mix with work ideas.
3. **No extraction/enrichment** — source material (reels, articles, screenshots) never becomes structured output. Place names in a reel never become a Maps-linked list; recipe reels never become shopping lists; article links never get summarized.

Result: most stray thoughts and links don't survive the day.

## User Personas

### Primary: the user (daily self-use, iPhone + MacBook)

- **Role:** power user of Claude Code; already built the home-finance-dashboard plugin; iCloud-native.
- **Goals:**
  - Capture from phone in ≤10s with minimal friction
  - Get structured, categorized, enriched output without manual sorting
  - Leverage across life domains (trips, reading, groceries, recipes, people, home, purchases, ideas)
  - Have captures update existing items (check off tasks, annotate list entries) using the same capture pipe
- **Frustrations:** re-typing places into Google Maps; losing reels; mixed-purpose Notes lists; no memory/context across captures; having to remember which list a thought belongs in.
- **Success looks like:** after 2 weeks, the default dumping-ground when a thought hits is this system, not Apple Notes.

## System Shape (orientation, not design)

Two-layer split:

- **Capture layer (iOS, phone-first)** — instant, dumb, reliable. Everything lands as raw payload in an iCloud Drive inbox folder. Zero categorization at capture time.
- **Processor layer (Mac, Claude Code plugin)** — manual `/process-inbox` command for MVP; reads inbox, applies preferences, extracts/enriches/categorizes, files into Markdown. Auto-processing is Post-MVP.

## Requirements

### Must Have (MVP)

**Capture layer (iOS):**

- [ ] REQ-001: Apple Shortcut accepts shared content from iOS Share Sheet: URL, image, text, voice-dictated text. Writes raw payload to iCloud Drive inbox folder, timestamped.
- [ ] REQ-002: Same Shortcut handles screenshots (Share Sheet from screenshot preview) — primary path for Instagram reels with overlay text.
- [ ] REQ-003: Home-screen Shortcut icon opens a quick-capture menu: paste link / pick image / dictate / type.
- [ ] REQ-004: Each capture prompts for an optional processing hint (free-text or voice-dictated) — e.g., "add to Japan trip", "just save as idea", "extract places". Stored alongside payload.
- [ ] REQ-005: Voice input converted to text via iOS on-device dictation inside the Shortcut. No external transcription service.
- [ ] REQ-006: Each capture stored atomically — one file (or folder) per capture, so processing is idempotent and safe to retry.

**Processor layer (Claude Code plugin, Mac):**

- [ ] REQ-007: `/process-inbox` slash command reads the iCloud Drive inbox folder and processes each item.
- [ ] REQ-008: For each item, processor uses: `WebFetch` for URL content; vision for images/screenshots (OCR + scene understanding); the **colleague skills under `agentic-systems/skills/`** for specific source types (see REQ-008c); the item's processing hint; and the persistent `CLAUDE.md`.
- [ ] REQ-008a: Processor is aware of per-source WebFetch limits and prefers the screenshot path where WebFetch is unreliable:
  - **Works well via WebFetch:** articles, blogs, tweets, Yelp/TripAdvisor, YouTube metadata (title/channel/description), Google Maps single-place links (`maps.app.goo.gl/...` → `og:title` + address).
  - **Unreliable via WebFetch — use screenshot path instead:** Instagram reels/posts (login wall / missing caption), TikTok, Google Maps saved lists (JS-rendered).
  - **Not supported in MVP:** Instagram video/audio content, TikTok audio, Google Maps list ingestion via API. (See Post-MVP REQ-021 / REQ-024.) _YouTube transcripts are covered in MVP via `youtube-fetch` — see REQ-008c._
- [ ] REQ-008b: When a URL is from an unreliable source and no screenshot was provided, processor saves what it could extract + flags the item in the end-of-run digest so the user can re-capture via screenshot.
- [ ] REQ-008c: **Leverage existing colleague skills at `/Users/mohtamadhukar/LocalDocuments/Github/agentic-systems/skills/`:**
  - **`youtube-fetch`** — for any YouTube URL (video or playlist). Returns metadata + full transcript as JSON. Uses `youtube-transcript-api` + `yt-dlp` internally. This promotes YouTube transcript extraction from Post-MVP to **in MVP** — one subprocess call, no bundled code needed.
  - **`pdf-to-markdown`** — when a capture is a PDF (receipts, booking confirmations, research). Converts to Markdown, feeds into the same extraction pipeline.
- [ ] REQ-008d: PDF captures handled: iOS Share Sheet → inbox writes the `.pdf` file; processor detects extension and calls `pdf-to-markdown` before extraction/categorization.
- [ ] REQ-009: Processor extracts structured info appropriate to the source: places (with Google Maps links), recipe ingredients + method, article 3-bullet summary, quote + attribution, product details (price, vendor, link).
- [ ] REQ-010: Processor picks the right output shape per item: **task** (`- [ ]`), **list entry** (bullet with enrichment), or **note** (freeform paragraph).
- [ ] REQ-011: Processor files each item into the correct category file. **Prefers existing files when a clean fit exists, but creates new files/folders freely when no existing file fits.** Categories emerge from captures; no pre-declared taxonomy required. When a new category is created, the processor notes it in the end-of-run digest so the user can review and (optionally) record a convention in `CLAUDE.md` later.
- [ ] REQ-012: The workspace-root `CLAUDE.md` is auto-loaded by Claude Code every run and shapes processing: dietary prefs, active trips/projects, tone, category conventions (as they emerge), person profiles for CRM/gift contexts, and sync-default pattern rules. Replaces the earlier `preferences.md` concept — same role, but auto-loaded by the harness instead of requiring an explicit read step.

**Update handling:**

- [ ] REQ-013: Processor detects whether a capture is a **new item** vs. an **update** to an existing item (e.g., "bought milk and eggs", "Ain Soph was amazing"). Fuzzy-matches against current file contents.
- [ ] REQ-014: For matched updates: checks off tasks (`- [ ]` → `- [x]`), appends ✓ + note to list entries. For ambiguous matches: flags for user review rather than guessing.
- [ ] REQ-015: End-of-run digest prints a short summary: N added, N closed, N ambiguous (with file paths).

**Storage:**

- [ ] REQ-016: All output is plain Markdown in a local folder (iCloud-synced or plain local). No external output integrations beyond REQ-026.
- [ ] REQ-017: **Folder structure is fluid, not prescriptive.** The workspace grows organically as captures arrive. Example shapes (NOT required up-front): topic dirs like `trips/<name>/`, flat files like `reading.md`, person files like `people/<name>.md`. The processor picks the shape that fits the capture; shapes below are illustrative, not a schema.

**Starter scope:**

- [ ] REQ-018: **Ship with an empty workspace plus a minimal `CLAUDE.md` skeleton** (Identity, Dietary, People sections populated; Category conventions section empty — fills in as the user develops patterns). No pre-seeded categories. First captures create the first files.

**Output sync (minimal, to prove workspace output reaches consumer apps):**

- [ ] REQ-026: **Output sync layer (narrow MVP).** After filing, the processor pushes touched workspace files to declared sync targets. **MVP targets: Apple Notes (push only) and Google Maps clickable links (local renderer, no API).** Sync runs at end of `/process-inbox`; failures are non-fatal.
- [ ] REQ-027: **Sync target declaration.** Each workspace file can declare sync targets in YAML frontmatter (`sync:` block). `CLAUDE.md` carries pattern-based defaults (e.g., `trips/*/vegan-spots.md → apple-notes + google-maps-links`). When Claude creates a new file, it consults pattern defaults and writes matching `sync:` frontmatter; if no pattern matches, it asks in the review phase.
- [ ] REQ-030: **Sync outcome reporting.** End-of-run digest reports per-target: N pushed, N errors. Sync failures are non-fatal (capture processing succeeded; retry next run).

### Should Have (Post-MVP)

_Only items that require actual system/code work. New **categories** (home, finance, people, workouts, etc.) are not listed here — by MVP design, those are added by editing `CLAUDE.md` and require no code changes._

- [ ] REQ-019: **Cross-file recipe → grocery.** Recipe captures automatically append any missing ingredients to `grocery.md`. Requires narrow fuzzy-match against existing lines; demoted to Post-MVP alongside general update detection.
- [ ] REQ-020: **Automatic processing** — scheduled cron or `fswatch` on the inbox folder; items processed without running `/process-inbox` manually.
- [ ] REQ-021: **Reel / TikTok audio transcription** — two-step pipeline: `yt-dlp` to pull media/auto-subs for Instagram/TikTok sources, fall back to the colleague `transcribe` skill (AssemblyAI) for sources without auto-subs. Needs `ASSEMBLYAI_API_KEY`, pay-per-minute.
- [ ] REQ-022: **Long-form voice memos** — for dictations exceeding iOS Shortcuts' ~60s dictation limit. Shortcut records audio file → processor calls `transcribe` skill.
- [ ] REQ-023: **Extra capture routes** — Back Tap trigger, Finder drag-and-drop on Mac, Raycast/Alfred command, pinned Apple Notes "Capture" note that the processor drains.
- [ ] REQ-024: **Google Maps list ingestion via Places API** — for importing a friend's shared Maps list when screenshots aren't practical. Requires API key + billing.
- [ ] REQ-025: **Open questions resolution** — whichever of the items in the "Open Questions" section below prove to be real problems in daily use get promoted here as concrete requirements.
- [ ] REQ-028: **Apple Reminders sync (push + shared round-trip).** Personal + shared Reminders lists with pull of check-state and collaborator-added items. Deferred: shared-list invite flow, text-match pull fragility, wording reconciliation.
- [ ] REQ-029: **Google Sheets sync.** Push tabular Markdown (tables or frontmatter `columns:` files) to a Google Sheet; OAuth + Drive sharing.

### Out of Scope

- External output integrations beyond Apple Notes + Google Maps clickable links in MVP (Notion, Todoist, etc.). Apple Reminders and Google Sheets are Post-MVP (REQ-028, REQ-029).
- Time-based reminders / notifications. Calendar + Reminders already own that job.
- Cross-device realtime sync beyond iCloud Drive.
- Medical / sensitive health tracking.
- Finance tracking that overlaps with the home-finance-dashboard plugin.
- Subscription tracking with expiration reminders.
- Instagram "Saved" collection scraping (no public API, brittle).
- Clipboard auto-watching (too many false positives).

## Success Criteria

- **Behavioral adoption (primary):** after 2 weeks of daily use, ≥80% of the user's daily thought/link/reel-sharing flow lands in this system instead of Apple Notes. Self-reported.
- **Processing quality:** on processed items, the user accepts Claude's categorization + output-shape choice without editing ≥80% of the time.
- **Extraction quality:** a captured reel screenshot with 5 restaurant names in overlay text becomes a Maps-linked list in the right trip folder within <60s of `/process-inbox` running.
- **Capture latency:** "I have a thought" → "it's in the inbox" in ≤3 taps or ≤10s of voice.
- **Recovery:** zero silent data loss — every inbox item is either filed, or flagged for review; nothing is dropped without a trace.

## Reference: External API / Source Landscape

_Recorded so future-us doesn't re-research this. Accurate as of 2026-04-23._

| Platform | Official API | Usable for ingestion? | Notes |
|---|---|---|---|
| **YouTube — metadata** | Data API v3 (free, 10k units/day) | ✅ Works, but WebFetch already yields title/channel/description free. API not worth the key. |
| **YouTube — transcripts** | None (official API doesn't expose others' auto-captions) | ❌ — use `yt-dlp --write-auto-subs` | Free, local, reliable. |
| **Instagram — public posts/reels** | Basic Display API **deprecated Dec 2024**. Graph API only works for Business/Creator accounts that explicitly authorized the app. | ❌ | Not usable for ingesting random reels. |
| **Instagram — oEmbed** | Public, requires FB App token | ⚠️ Caption + embed HTML only | Not worth the setup vs. screenshot path. |
| **Facebook** | Graph API (auth + app review) | ❌ | Same reason as IG. |
| **TikTok** | Content Posting API (for posting *to* TT) + Research API (academics only) | ❌ | No public ingestion path. |
| **Google Maps — single place** | Places API (New), paid, billing required | ⚠️ Overkill | WebFetch of short/long Maps URLs already yields place name + address via `og:` tags. |
| **Google Maps — saved lists** | **No API exists** | ❌ Screenshot is the only route | Google never opened a shared-list API. |
| **X / Twitter** | API paid ($100/mo min) | ❌ | Not viable for a personal tool. |
| **Reddit** | Free with OAuth, 60 req/min | ✅ Cheap if needed later | Not in MVP. |
| **Articles / blogs / Yelp / TripAdvisor / etc.** | — | ✅ WebFetch works well | No API needed. |

**Key insight:** big-platform APIs are designed for businesses to **post content TO the platform**, not for users to **ingest content FROM the platform**. This is deliberate — Instagram Basic Display was killed specifically to prevent third-party ingestion.

**`yt-dlp` is the one high-leverage unofficial escape hatch.** Single local binary, no auth, no keys, covers YouTube + Instagram + TikTok + Twitter + Reddit + 1000+ other sites. Downloads video + auto-subs. ToS-grey on some platforms, but fine for personal, non-redistributed use. Already used internally by `youtube-fetch` (MVP); queued for Instagram/TikTok ingestion as **REQ-021** (Post-MVP).

**Strategy for MVP:** skip every official API. WebFetch + vision (screenshots) covers ~95% of captures. Only consider APIs when a concrete recurring need emerges.

## Reference: Colleague Skills We Can Leverage

_Skills available at `/Users/mohtamadhukar/LocalDocuments/Github/agentic-systems/skills/`. Standalone Python/bash skills — call them from the processor as subprocesses, don't rewrite._

| Skill | What it does | Fit for lazyhuman-ai |
|---|---|---|
| **`youtube-fetch`** | YouTube transcript + metadata via `youtube-transcript-api` + `yt-dlp`. Single video or whole playlist. JSON output. | ✅ **MVP** — plugs into REQ-008c. Closes the YouTube gap. |
| **`pdf-to-markdown`** | PDF → Markdown via PyMuPDF4LLM. Batches, page ranges. | ✅ **MVP** — enables PDF captures (receipts, bookings, research menus). REQ-008d. |
| **`transcribe`** | Audio/video transcription with speaker diarization (AssemblyAI). Supports `.m4a/.mp3/.wav/.mp4/.webm`. Needs `ASSEMBLYAI_API_KEY`, pay-per-minute. | ⚠️ **Post-MVP (REQ-021, REQ-022)** — reel audio + long-form voice memos beyond iOS dictation's ~60s limit. |
| **`watch-youtube`** | Full multimodal YouTube: downloads, frames, OCR, LLM-enrichment. 3-8 min/video, needs `OPENAI_API_KEY`. | ❌ Skip — overkill. `youtube-fetch` suffices. |
| **`web-corpus`** | Searchable local corpora from crawled sites (FTS + semantic, Playwright for JS sites). | ⚠️ Adjacent — not needed for single-capture processing. Useful separately if the user ever wants to ingest an entire blog (e.g. Japan vegan site) into a local searchable KB. |
| **`audio-capture`** | System audio + mic background recording on Mac (ffmpeg + BlackHole). | ❌ Not relevant (designed for meeting recordings). |
| `slides-to-pptx`, `markdown-slides`, `html-slides`, `generate-podcast`, `ralphify`, `lesson-video`, `outlook` | — | ❌ Different domains. |

**Integration principle:** call skills as subprocesses from the processor. Don't copy their code. Pin to a known-good state of the `agentic-systems` repo, or document its absolute path in a config file so the processor can locate the skill scripts reliably.

## Open Questions

- **Inbox file layout:** folder-per-day with one file per capture (recommended), vs. one rolling file, vs. flat timestamped files. Folder-per-day is easiest to reason about atomically.
- **Processing hint storage:** front-matter in the capture file (recommended) vs. a sibling `.hint` file.
- **Workspace `CLAUDE.md` structure:** single file to start (recommended), split into sub-files referenced from the root CLAUDE.md if it grows past ~200 lines.
- **Ambiguous-match behavior:** should the processor wait for user review before filing, or file-with-asterisk and let the user audit in the digest? (Recommend the latter — never block processing.)
- **Multi-device capture conflicts:** two captures arriving at the same timestamp from iPhone + Mac — filename collision handling. Trivial fix (append suffix) but worth calling out.
