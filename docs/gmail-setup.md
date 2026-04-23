# Gmail setup

Authentication uses an **app password over IMAP** — no Google Cloud project needed.

## 1. Enable 2-Step Verification

App passwords require 2-Step Verification on the Google account. Turn it on at
<https://myaccount.google.com/security>.

## 2. Create an app password

1. Go to <https://myaccount.google.com/apppasswords>.
2. Name it `lazyhuman-ai` (or anything descriptive).
3. Copy the 16-character password Google shows you — you will not see it again.

## 3. Make sure IMAP is enabled

In Gmail: ⚙️ Settings → **See all settings** → **Forwarding and POP/IMAP** →
set **IMAP access: Enable IMAP** and save.

## 4. Create labels and a filter

Labels (Gmail → left sidebar → **+** next to "Labels"):

- `lazyhuman/inbox` (nest under `lazyhuman`)
- `lazyhuman/processed` (nest under `lazyhuman`)

Filter (Gmail → search bar → show search options):

- **To:** `your+lh@gmail.com`
- **Subject:** `[LH]`
- Action: **Apply the label** `lazyhuman/inbox`, **Skip the Inbox**, **Also apply filter to matching conversations**.

## 5. Configure the plugin

```bash
cp config.example.json config.json   # edit: gmail_address, workspace_dir, local_inbox_dir
cp .env.example .env                  # edit: paste the 16-char app password
```

Both files are git-ignored.

## 6. Smoke test

Send yourself a message matching the filter. Check it lands under
`lazyhuman/inbox`, then run:

```bash
python3 -m scripts.drain_gmail
```

You should see a JSON manifest on stdout and a new folder under
`<local_inbox_dir>/<today>/`.
