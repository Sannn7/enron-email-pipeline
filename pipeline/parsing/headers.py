"""Header access on top of the stdlib parser (Plan step 4).

Enron files end header lines with CRLF and body lines with LF, so the header
block must never be found by splitting on a raw "\\n\\n"; the stdlib parser
handles both line endings.
"""
from __future__ import annotations

import email
import re
from email.message import Message
from email.policy import compat32

FOLD = re.compile(r"[ \t]*\r?\n[ \t]+")
SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
WS = re.compile(r"\s+")


def parse_message(text: str) -> Message:
    return email.message_from_string(text, policy=compat32)


def unfold(value: str) -> str:
    """Join folded continuation lines with a single space; keep other whitespace as written."""
    return FOLD.sub(" ", value).strip()


def get_header(msg: Message, name: str, keep_empty: bool = False) -> str | None:
    """First occurrence of a header, unfolded. Absent -> None; empty -> None unless keep_empty."""
    value = msg.get(name)
    if value is None:
        return None
    value = unfold(str(value))
    if value or keep_empty:
        return value
    return None


def get_all_headers(msg: Message, name: str) -> list[str]:
    """Every occurrence of a header (e.g. two To: lines), unfolded."""
    return [unfold(str(v)) for v in msg.get_all(name) or []]


def get_body(msg: Message) -> str:
    """Body text with line endings normalized to LF; multipart parts are concatenated."""
    payload = msg.get_payload()
    if isinstance(payload, list):
        payload = "\n".join(str(part.get_payload()) for part in payload)
    return str(payload or "").replace("\r\n", "\n")


def normalize_subject(subject: str | None) -> str:
    """Strip repeated leading Re:/Fw:/Fwd: (any case), collapse whitespace, lowercase."""
    return WS.sub(" ", SUBJECT_PREFIX.sub("", subject or "")).strip().lower()
