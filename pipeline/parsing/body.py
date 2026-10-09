"""Body split, attachment detection and similarity text (Plan step 7).

Split rule (decided at fixture review): the FIRST marker wins and everything
from it onward goes into one field.
  - Lotus "---- Forwarded by ..."           -> forwarded_content
  - Outlook "-----Original Message-----"   -> quoted_content,
    or forwarded_content when the subject starts with FW:/Fwd:
  - ">" lines before the first marker      -> quoted_content
Bodies are stored as written; quoted-printable artifacts are cleaned only in
normalize_for_similarity().
"""
from __future__ import annotations

import hashlib
import re

OUTLOOK = re.compile(r"^[ \t>]*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE | re.MULTILINE)
LOTUS = re.compile(r"^[ \t>]*-{3,}\s*Forwarded by", re.IGNORECASE | re.MULTILINE)
FW_SUBJECT = re.compile(r"^\s*(fw|fwd)\s*:", re.IGNORECASE)

# "<<file.doc>>" (Lotus) and "<< File: file.doc >>" (Outlook)
ATTACHMENT_REF = re.compile(r"<<\s*(?:File:\s*)?([^<>\n]+?\.[A-Za-z0-9]{2,5})\s*>>")
ATTACHMENT_EXTS = ("doc|docx|xls|xlsx|ppt|pps|pdf|jpg|jpeg|gif|bmp|tif|txt|zip|wpd|csv|rtf|"
                   "htm|html|msg|vsd|dot|mpp")
# Lotus attachment listing: a line like " - report.pdf"
ATTACHMENT_DASH = re.compile(rf"^\s*-\s+(\S[^\n]*?\.(?:{ATTACHMENT_EXTS}))\s*$", re.IGNORECASE | re.MULTILINE)

QP_SOFT_BREAK = re.compile(r"=\n")
QP_CODES = {"=20": " ", "=3D": "=", "=09": "\t"}
WS = re.compile(r"\s+")


def split_body(body: str, subject: str | None = "") -> tuple[str, str | None, str | None]:
    """Return (primary, forwarded_content, quoted_content), each stripped; empty parts are None."""
    marks = [(m.start(), kind) for kind, rx in (("quoted", OUTLOOK), ("forwarded", LOTUS))
             for m in [rx.search(body)] if m]
    cut, kind = min(marks) if marks else (len(body), None)
    if kind == "quoted" and FW_SUBJECT.match(subject or ""):
        kind = "forwarded"
    head, tail = body[:cut], body[cut:].strip()

    lines = head.splitlines()
    primary = "\n".join(l for l in lines if not l.lstrip().startswith(">")).strip()
    gt_quoted = "\n".join(l for l in lines if l.lstrip().startswith(">")).strip()

    quoted_parts = [gt_quoted, tail if kind == "quoted" else ""]
    quoted = "\n\n".join(p for p in quoted_parts if p) or None
    forwarded = (tail or None) if kind == "forwarded" else None
    return primary, forwarded, quoted


def find_attachments(body: str) -> list[str]:
    """Attachment filenames referenced in the body, de-duplicated in order of appearance."""
    names = [n.strip() for n in ATTACHMENT_REF.findall(body)
             if "mailto:" not in n.lower() and "@" not in n and "://" not in n]
    names += [n.strip() for n in ATTACHMENT_DASH.findall(body)]
    return list(dict.fromkeys(names))


def content_type_implies_attachment(content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    return "multipart" in ct or "name=" in ct


def full_body_hash(body: str) -> str:
    """Body part of the folder-copy key: sha1 of the whole body with whitespace collapsed.

    Same definition as scripts/mailbox_profile.py so README numbers match the pipeline.
    """
    return hashlib.sha1(WS.sub(" ", body).strip().encode("utf-8", "surrogateescape")).hexdigest()


def normalize_for_similarity(text: str | None) -> str:
    """Text used only for similarity: QP artifacts cleaned, whitespace collapsed."""
    if not text:
        return ""
    text = QP_SOFT_BREAK.sub("", text.replace("\r\n", "\n"))
    for code, ch in QP_CODES.items():
        text = text.replace(code, ch)
    return WS.sub(" ", text).strip()
