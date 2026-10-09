"""Duplicate-notice text, following the spec template exactly (Plan step 14).

Subject rule (avoids "Re: Re:"): start from the ORIGINAL email's subject as the
spec says; if it already begins with "Re:" (any case, after trimming) it is used
as written, otherwise "Re: " is prepended. An empty subject becomes "(no subject)".
  "Forecast"      -> "[Duplicate Notice] Re: Forecast"
  "RE: Forecast"  -> "[Duplicate Notice] RE: Forecast"
  "Fwd: Forecast" -> "[Duplicate Notice] Re: Fwd: Forecast"
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

RE_PREFIX = re.compile(r"^\s*re\s*:", re.IGNORECASE)

BODY_TEMPLATE = """\
This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {dup_id}
    Date Sent:   {dup_date}
    Subject:     {dup_subject}

  Original Email on Record:
    Message-ID:  {orig_id}
    Date Sent:   {orig_date}

  Similarity Score: {score:.2f}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
"""


def notice_subject(original_subject: str | None) -> str:
    subject = (original_subject or "").strip() or "(no subject)"
    if RE_PREFIX.match(subject):
        return f"[Duplicate Notice] {subject}"
    return f"[Duplicate Notice] Re: {subject}"


def reply_filename(duplicate_message_id: str) -> str:
    return f"reply_{hashlib.sha256(duplicate_message_id.encode('utf-8')).hexdigest()[:16]}.eml"


@dataclass
class Notification:
    to: str                    # sender of the flagged duplicate (real Enron address)
    subject: str
    references: str            # Message-ID of the flagged duplicate
    body: str
    duplicate_message_id: str
    original_message_id: str


def build_notification(dup: dict, orig: dict) -> Notification:
    """dup/orig: rows with message_id, date, subject, from_address (+ dup similarity_score)."""
    body = BODY_TEMPLATE.format(
        dup_id=dup["message_id"], dup_date=dup["date"], dup_subject=dup["subject"],
        orig_id=orig["message_id"], orig_date=orig["date"], score=float(dup["similarity_score"]),
    )
    return Notification(
        to=dup["from_address"],
        subject=notice_subject(orig["subject"]),
        references=dup["message_id"],
        body=body,
        duplicate_message_id=dup["message_id"],
        original_message_id=orig["message_id"],
    )
