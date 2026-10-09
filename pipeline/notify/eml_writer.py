"""Dry-run output: one reply_<hash>.eml per flagged duplicate (Plan step 14, decision D8)."""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from pipeline.notify.template import Notification, reply_filename


def to_eml(n: Notification, now: datetime) -> bytes:
    msg = EmailMessage()
    msg["To"] = n.to
    msg["Subject"] = n.subject
    msg["Date"] = format_datetime(now.astimezone(timezone.utc))
    msg["References"] = n.references
    msg.set_content(n.body)
    return msg.as_bytes()


def write_all(notifications: list[Notification], replies_dir: Path, now: datetime) -> int:
    """Replace the contents of replies_dir with one .eml per notification; returns the count."""
    replies_dir.mkdir(parents=True, exist_ok=True)
    for stale in replies_dir.glob("reply_*.eml"):
        stale.unlink()
    for n in notifications:
        (replies_dir / reply_filename(n.duplicate_message_id)).write_bytes(to_eml(n, now))
    return len(notifications)
