---
description: Re-sync every workspace file with a sync target declared in its frontmatter (Apple Notes, etc.).
---

# /sync-outputs

Full resync. Useful after editing `CLAUDE.md` sync defaults, or after bulk
edits to workspace files.

Run:

```bash
python3 -m scripts.sync_push --all
```

Parse the JSON summary on stdout and show it to the user as a short report —
per target, `{pushed, errors}`. If any errors are listed, show them verbatim.
