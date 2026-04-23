"""Thin IMAP wrapper over Gmail.

Uses app-password auth (see `docs/gmail-setup.md`) rather than OAuth.
Gmail labels are exposed as IMAP folders; label membership
can be mutated via Gmail's `X-GM-LABELS` extension (which imapclient's
`add_gmail_labels` / `remove_gmail_labels` / `move` wrap).

Each message has a stable `X-GM-MSGID` (a 64-bit int) that lets us
re-find it across folders — we stash that in meta.json so file_item.py
can flip labels on the right message later.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from imapclient import IMAPClient

from scripts._lib.config import load_config, load_gmail_secret

IMAP_HOST = "imap.gmail.com"
ALL_MAIL = "[Gmail]/All Mail"


def imap_connect() -> IMAPClient:
    cfg = load_config()
    secret = load_gmail_secret()
    addr = cfg["gmail_address"]
    pw = secret["app_password"]
    c = IMAPClient(IMAP_HOST, ssl=True)
    try:
        c.login(addr, pw)
    except Exception as e:  # noqa: BLE001
        c.logout()
        raise SystemExit(
            f"Gmail IMAP login failed for {addr}: {e}. "
            f"Check that the app password is correct and IMAP is enabled."
        ) from e
    return c


@contextmanager
def imap_session() -> Iterator[IMAPClient]:
    c = imap_connect()
    try:
        yield c
    finally:
        try:
            c.logout()
        except Exception:  # noqa: BLE001
            pass


def list_uids(conn: IMAPClient, folder: str) -> list[int]:
    """Return UIDs of all messages in `folder` (a Gmail label)."""
    conn.select_folder(folder, readonly=False)
    return list(conn.search(["ALL"]))


def fetch_rfc822(conn: IMAPClient, uid: int) -> tuple[bytes, int | None]:
    """Returns (raw_rfc822_bytes, gm_msgid).

    Requires a folder to be currently selected.
    """
    resp = conn.fetch([uid], [b"RFC822", b"X-GM-MSGID"])
    data = resp.get(uid, {})
    raw = data.get(b"RFC822", b"")
    gm_msgid = data.get(b"X-GM-MSGID")
    return raw, (int(gm_msgid) if gm_msgid is not None else None)


def find_uid_by_gm_msgid(conn: IMAPClient, folder: str, gm_msgid: int) -> int | None:
    """Search for a message by X-GM-MSGID within `folder`. Returns UID or None."""
    conn.select_folder(folder, readonly=False)
    uids = conn.search(["X-GM-MSGID", gm_msgid])
    return uids[0] if uids else None


def move_by_gm_msgid(
    conn: IMAPClient, gm_msgid: int, src_folder: str, dst_folder: str
) -> bool:
    """Move a message from `src_folder` to `dst_folder` (by X-GM-MSGID).

    In Gmail-IMAP terms, this swaps the src label for the dst label and
    preserves all other labels on the message. Returns True if moved,
    False if not found in src.
    """
    uid = find_uid_by_gm_msgid(conn, src_folder, gm_msgid)
    if uid is None:
        return False
    conn.move([uid], dst_folder)
    return True
