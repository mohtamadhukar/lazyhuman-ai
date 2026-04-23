# iOS Shortcut: lazyhuman-ai capture

_Build the "lazyhuman-ai" Apple Shortcut that turns any Share Sheet payload or home-screen tap into an email to your dedicated Gmail plus-address._

## Goal

After following this doc, you can:

1. Share anything from iOS (URL, image, screenshot, PDF, selected text) → Share Sheet → **lazyhuman-ai** → email with structured JSON meta block lands in Gmail.
2. Tap a home-screen icon → pick-a-capture-method menu (paste link / pick image / dictate / type) → same outcome.
3. Each capture is labeled `lazyhuman/inbox` in Gmail (via the filter from `gmail-setup.md`).

## Prerequisites

- [ ] A Gmail account configured in **Settings → Mail → Accounts** on your iPhone. The Shortcut's `Send Email` action uses whatever accounts are set up in Mail.app — it will **not** work without one.
- [ ] The Gmail filter from [`gmail-setup.md`](./gmail-setup.md) is set up and verified (send a test email to `<you>+lh@gmail.com`, confirm the `lazyhuman/inbox` label gets applied). Do this **before** building the Shortcut so you can verify end-to-end as you go.
- [ ] iOS 17 or later (the `Show When Run: Off` headless-send behavior is the default on iOS 17+; older versions may still prompt).

## One-time config you'll set inside the Shortcut

- `CAPTURED_BY`: a short string identifying this phone (e.g. `"madhukar"` on your iPhone, `"priya"` on your wife's iPhone). Hardcoded as a **Text** action at the top of the Shortcut. Set once per install.
- `GMAIL_ADDRESS`: your plus-address target, e.g. `mohtamadhukar+lh@gmail.com`. Also a **Text** action at the top.

## Build steps

Open **Shortcuts** app → **+** → rename the shortcut to **lazyhuman-ai**.

### 1. Config block (first four actions)

`Set Variable` on its own can't hold a literal string — its value is always the previous action's output (labeled "Input"). So you pair each `Set Variable` with a `Text` action that produces the literal. Two pairs, in this order:

1. **Text** → content: `madhukar`.
2. **Set Variable** → Variable Name: `CAPTURED_BY`. The Input field auto-picks up the Text action's output (purple "Text" pill) — leave it.
3. **Text** → content: `mohtamadhukar+lh@gmail.com`.
4. **Set Variable** → Variable Name: `GMAIL_ADDRESS`. Input auto-picks up the second Text action.

After these four actions, both named variables are available to every later action via the variable picker strip above the keyboard.

### 2. Detect invocation path (Share Sheet vs. home screen)

In the Shortcut's settings (⓵ icon at top):

- [ ] Turn on **Show in Share Sheet**.
- [ ] **Share Sheet Types**: select **URLs, Text, Images, PDFs** (tap each to enable). Leave the rest off.
- [ ] **Receive [types] from Share Sheet**, "If there's no input, ask for …" → **Nothing** (we'll handle empty input ourselves).

Now add the branching:

3. **If** → Condition: **Shortcut Input** → **has any value**.

   Inside the **If** branch (Share Sheet path):

4. **Set variable** → name: `PAYLOAD` → value: **Shortcut Input**.

   **Otherwise** branch (home-screen path):

5. **Choose from Menu** → Prompt: `Capture…`
   Items:
   - `Paste link`
   - `Pick image`
   - `Dictate`
   - `Type`

   Inside each menu case:

   - **Paste link** case:
     - **Get Clipboard** → **Set variable** `PAYLOAD` to **Clipboard**.
   - **Pick image** case:
     - **Select Photos** (allow multiple: off) → **Set variable** `PAYLOAD` to **Photos**.
   - **Dictate** case:
     - **Dictate Text** (Language: English, Stop Listening: **On Tap**) → **Set variable** `PAYLOAD` to **Dictated Text**.
   - **Type** case:
     - **Ask for Input** (Input Type: Text, Prompt: `What's the capture?`) → **Set variable** `PAYLOAD` to **Provided Input**.

6. **End If**.

### 3. Ask for the processing hint

7. **Ask for Input**:
   - Input Type: **Text**
   - Prompt: `Optional hint (or leave blank)`
   - Default Answer: (empty)
   - Allow Multiple Lines: **On**
   - Tip: iOS shows a dictation mic on the keyboard — useful for voice-driven hints.
   - → **Set variable** `HINT` to **Provided Input**.

### 4. Build the capture `id`

iOS Shortcuts doesn't natively emit hex; we use a 4-digit decimal suffix instead. Same collision properties (10⁴ per second is plenty for one person's captures).

8. **Current Date** → **Format Date**:
   - Date Format: **Custom**
   - Custom Format String: `yyyyMMdd-HHmmss`
   - → **Set variable** `TS` to **Formatted Date**.

9. **Random Number** → Min: `1000`, Max: `9999` → **Set variable** `RND` to **Random Number**.

10. **Text** → value: `[TS]-[RND]`
    (insert the `TS` and `RND` variables via the variable picker, not typed literally)
    → **Set variable** `ID` to **Text**.

### 5. Set `kind` to "auto" and extract `source_url`

**Design change from original plan.** iOS Shortcuts' type-extraction actions (`Get URLs from Input`, `Get Images from Input`, etc.) are unreliable across iOS versions and Share Sheet sources — especially for composite items like Instagram reels. Instead of detecting `kind` in the Shortcut, we punt it to the Mac-side processor, which can inspect the email attachment's MIME type and infer `kind` with 100% accuracy.

The Shortcut's only job for these fields: hard-code `kind: "auto"` and do a dumb "contains http" check for `source_url`.

11. **Text** → content: `auto`. **Set Variable** → Name = `KIND`, input = that Text.
12. **Text** → content: just the **Shortcut Input** variable pill. **Set Variable** → Name = `URL_CAND`.
13. **If** → Input = **URL_CAND**; Condition = **starts with**; Value = `http`.
    - **Inside If**: **Set Variable** → Name = `SOURCE_URL`, input = **URL_CAND**.
    - **Inside Otherwise**: **Text** (empty content) → **Set Variable** → Name = `SOURCE_URL`, input = that empty Text.

    _(Matches both `http://` and `https://`, no false positives from hints that merely mention the word "http".)_

    **Note:** URL shares from rich sources (Safari, Instagram, YouTube) carry extra attachments — preview images, favicons, page content. The Shortcut sends these through as-is; `drain_gmail.py` filters them server-side. See PLAN Phase 2 Step 2.3 for the filter logic.

No `Get URLs from Input`, no `Get Images from Input`, no nested list handling. The processor handles type inference from the MIME side.

### 7. Build the JSON meta block

14. **Get Current Date** → **Format Date**: ISO 8601 (Shortcuts has a preset: "ISO 8601 Date" — use **Include Time: On**) → **Set variable** `CAPTURED_AT`.

15. **Dictionary** → add these keys (all values come from variables):
    - `id` → `ID`
    - `captured_at` → `CAPTURED_AT`
    - `captured_by` → `CAPTURED_BY`
    - `kind` → `KIND`
    - `source_url` → `SOURCE_URL`
    - `hint` → `HINT`
    - _(source_app is best-effort and hard to get reliably from Shortcuts; skip for MVP, the processor treats missing keys as empty)_

16. **Get Dictionary as JSON** → **Set variable** `META_JSON`.

### 8. Build the email body

17. **Text** →
    ```
    ```json
    [META_JSON]
    ```

    [PAYLOAD if KIND is text, else empty]
    ```
    (three backticks + `json`, newline, the `META_JSON` variable, newline, three backticks, blank line, then `PAYLOAD` only if `KIND` is `text`. For non-text kinds, the body is just the json block.)

    Easiest way to do the conditional-append: use another **If** `KIND` is `text` → append `PAYLOAD` to a `BODY` text var; else `BODY` = just the JSON block.

    → **Set variable** `BODY`.

### 9. Build the subject

18. **Text** → `[LH] [ID]` → **Set variable** `SUBJECT`.

### 10. Send the email

19. **Send Email**:
    - Recipients: `GMAIL_ADDRESS`
    - Subject: `SUBJECT`
    - **Message**: insert the **BODY** variable, then press Return, then insert the **PAYLOAD_ATTACH** variable as a second pill. The Message field accepts stacked variables — Mail.app treats any non-text variable (image/PDF/file) as an attachment. There is **no separate Attachments field** in modern iOS Shortcuts; attachments come via the Message field. (For URL shares, `PAYLOAD_ATTACH` is empty so no page assets get attached.)
    - Tap **∨** to expand the action.
    - **Show When Run**: **Off** (critical — makes the send headless)
    - From: pick your Gmail account from the dropdown (only appears if Gmail is configured in Mail.app).

### 11. (Optional) Add a success haptic

20. **Vibrate Device** (or a **Show Notification** with text `Captured ✓` if you want visible confirmation while testing).

## Home-screen icon

1. Open the Shortcuts app → long-press **lazyhuman-ai** → **Details** → **Add to Home Screen**.
2. Pick an icon / name (e.g. 🧠 LH).
3. Tapping it runs the Shortcut with **no Shortcut Input**, triggering the home-screen menu path (step 2 above).

## Smoke test (no Mac code required yet)

- [ ] **Text capture (home-screen path)**: tap the home-screen icon → **Type** → `testing lazyhuman` → blank hint → check Gmail. An email with subject `[LH] 20260423-143021-3847` (or similar) lands, labeled `lazyhuman/inbox`, body contains a ```json ... ``` block with `id`, `captured_at`, `captured_by: "madhukar"`, `kind: "text"`, `hint: ""`, and `testing lazyhuman` below the block.
- [ ] **URL capture (Share Sheet path)**: open Safari on any article → Share Sheet → **lazyhuman-ai** → hint `save for later`. Check Gmail: json block has `kind: "url"` and `source_url` populated.
- [ ] **Screenshot capture**: take a screenshot → tap preview → Share → **lazyhuman-ai** → no hint. Check Gmail: json block has `kind: "image"`, and the PNG is attached.
- [ ] **PDF capture**: share any PDF (e.g. from Files) → **lazyhuman-ai**. Json block has `kind: "pdf"`, PDF is attached.
- [ ] **Filter check**: in Gmail web UI, open `lazyhuman/inbox` label — all four test captures are present.

If all four land correctly with the `lazyhuman/inbox` label applied, the capture side is done. Any Mac-side issues from here are in `drain_gmail.py` territory.

## Common snags

- **"Send Email couldn't send" popup.** Gmail account isn't configured in Mail.app, or Mail.app has no default account. Fix: Settings → Mail → Accounts → add/repair the Gmail account.
- **Shortcut prompts every time despite Show When Run: Off.** iOS shows a one-time privacy prompt on first send from a new Shortcut — allow it. If it keeps prompting, toggle Show When Run off explicitly in the Send Email action's detail view (not just the top-level settings).
- **Attachment missing on arrival.** `PAYLOAD` was set via a variable reference that lost its binary data. Double-check step 4 (If branch) — `PAYLOAD` must be set directly from **Shortcut Input** or **Select Photos** output, not from an intermediate Text action.
- **Label not applied.** The Gmail filter condition is `to:(<you>+lh@gmail.com)` — confirm the `+lh` suffix matches what `GMAIL_ADDRESS` contains in the Shortcut. Filters run on arrival only; messages that arrive before the filter is created don't get retroactively labeled (use "Also apply filter to matching conversations" when creating).
- **JSON block is one giant line with escaped quotes in the email body.** That's fine — `drain_gmail.py` parses it with a regex that doesn't care about whitespace. Don't try to pretty-print it inside the Shortcut.

## What's next

Once all four smoke-test captures land in Gmail with the right label, the iOS side is done. The Mac-side processor (`/process-inbox` command) will drain these messages next.
