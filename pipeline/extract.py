"""One file -> EmailRecord or ParseFailure (Plan step 8). Never raises."""
from __future__ import annotations

from pathlib import Path

from pipeline import models
from pipeline.copies import copy_key, copy_key_digest
from pipeline.models import EmailRecord, ParseFailure
from pipeline.parsing.addresses import parse_address_list
from pipeline.parsing.body import (content_type_implies_attachment, find_attachments, full_body_hash,
                                   split_body)
from pipeline.parsing.dates import parse_date, to_iso_utc
from pipeline.parsing.decode import decode_bytes
from pipeline.parsing.headers import (get_all_headers, get_body, get_header, normalize_subject,
                                      parse_message)


def extract_file(path: Path, source_file: str) -> EmailRecord | ParseFailure:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return ParseFailure(source_file, models.UNREADABLE, str(exc))
    try:
        return extract_text(decode_bytes(raw), source_file)
    except Exception as exc:  # one bad file must never stop the run
        return ParseFailure(source_file, models.PARSE_ERROR, f"{type(exc).__name__}: {exc}")


def extract_text(text: str, source_file: str) -> EmailRecord | ParseFailure:
    msg = parse_message(text)

    message_id = get_header(msg, "Message-ID")
    if not message_id:
        return ParseFailure(source_file, models.MISSING_MESSAGE_ID, "Message-ID header absent or empty")

    raw_date = get_header(msg, "Date")
    if not raw_date:
        return ParseFailure(source_file, models.MISSING_DATE, "Date header absent or empty")
    date = parse_date(raw_date)
    if date is None:
        return ParseFailure(source_file, models.UNPARSEABLE_DATE, f"Date: {raw_date!r}")

    senders = parse_address_list(get_all_headers(msg, "From"))
    if not senders:
        return ParseFailure(source_file, models.MISSING_FROM, "From header absent or has no address")

    to_headers = get_all_headers(msg, "To")
    to = parse_address_list(to_headers)
    if not to:
        detail = "To header absent" if not to_headers else f"To header has no address: {to_headers[0][:80]!r}"
        return ParseFailure(source_file, models.MISSING_TO, detail)

    subject = get_header(msg, "Subject", keep_empty=True)
    if subject is None:
        return ParseFailure(source_file, models.MISSING_SUBJECT, "Subject header absent")

    body_text = get_body(msg)
    primary, forwarded, quoted = split_body(body_text, subject)
    content_type = get_header(msg, "Content-Type")
    attachments = find_attachments(body_text)

    return EmailRecord(
        message_id=message_id,
        date=to_iso_utc(date),
        from_address=senders[0],
        to_addresses=to,
        subject=subject,
        body=primary,
        source_file=source_file,
        normalized_subject=normalize_subject(subject),
        body_hash=full_body_hash(body_text),
        copy_key=copy_key_digest(copy_key(msg.get("From"), msg.get("Date"), msg.get("Subject"), body_text)),
        cc_addresses=parse_address_list(get_all_headers(msg, "Cc")) or None,
        bcc_addresses=parse_address_list(get_all_headers(msg, "Bcc")) or None,
        x_from=get_header(msg, "X-From"),
        x_to=get_header(msg, "X-To"),
        x_cc=get_header(msg, "X-cc"),
        x_bcc=get_header(msg, "X-bcc"),
        x_folder=get_header(msg, "X-Folder"),
        x_origin=get_header(msg, "X-Origin"),
        content_type=content_type,
        has_attachment=bool(attachments) or content_type_implies_attachment(content_type),
        attachments=attachments,
        forwarded_content=forwarded,
        quoted_content=quoted,
        in_reply_to=get_header(msg, "In-Reply-To"),
        references=get_header(msg, "References"),
    )
