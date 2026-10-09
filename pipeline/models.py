"""Records produced by extraction."""
from __future__ import annotations

from dataclasses import dataclass, field

# ParseFailure.reason values
UNREADABLE = "unreadable"
PARSE_ERROR = "parse_error"
MISSING_MESSAGE_ID = "missing_message_id"
MISSING_DATE = "missing_date"
UNPARSEABLE_DATE = "unparseable_date"
MISSING_FROM = "missing_from"
MISSING_TO = "missing_to"
MISSING_SUBJECT = "missing_subject"


@dataclass
class EmailRecord:
    # mandatory
    message_id: str
    date: str  # ISO-8601 UTC, e.g. "2001-05-14T23:39:00Z"
    from_address: str
    to_addresses: list[str]
    subject: str
    body: str
    source_file: str  # e.g. "maildir/lay-k/inbox/45."
    # derived
    normalized_subject: str = ""
    body_hash: str = ""  # sha1 of the full body (all parts), whitespace collapsed
    copy_key: str = ""   # digest of pipeline.copies.copy_key()
    # optional
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    x_from: str | None = None
    x_to: str | None = None
    x_cc: str | None = None
    x_bcc: str | None = None
    x_folder: str | None = None
    x_origin: str | None = None
    content_type: str | None = None
    has_attachment: bool = False
    attachments: list[str] = field(default_factory=list)
    forwarded_content: str | None = None
    quoted_content: str | None = None
    in_reply_to: str | None = None
    references: str | None = None


@dataclass
class ParseFailure:
    source_file: str
    reason: str
    detail: str = ""
