"""Profile candidate mailboxes to choose the main 5 (Plan step 0.2, selection).

Read-only and deliberately rough: uses the stdlib email parser, not the
pipeline parser. Metrics are computed on emails AFTER collapsing folder copies
(same sender, timestamp, normalized subject, body hash) using the pipeline's
shared pipeline.copies.copy_key().

Usage:
    python scripts/mailbox_profile.py [--maildir data/maildir] [--mailboxes a,b,...]
                                      [--combo a,b,c,d,e] [--csv output/mailbox_profile.csv]
"""
from __future__ import annotations

import argparse
import csv
import email
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from email.policy import compat32
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.copies import copy_key as shared_copy_key  # noqa: E402  single copy definition

# Shortlist by role (roles from public Enron org knowledge; metrics verify fit).
CANDIDATES = {
    "lay-k": "executive",
    "skilling-j": "executive",
    "haedicke-m": "legal",
    "sager-e": "legal",
    "arnold-j": "trader",
    "allen-p": "trader",
    "grigsby-m": "trader",
    "steffes-j": "policy",
    "shapiro-r": "policy",
    "beck-s": "operations",
    "farmer-d": "operations",
}

SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
FORWARD_MARKER = re.compile(r"-{2,}\s*original message\s*-{2,}|forwarded by", re.IGNORECASE)
QUOTED_LINE = re.compile(r"^\s*>", re.MULTILINE)
ATTACHMENT_REF = re.compile(r"<<\s*[^<>\n]+?\.[A-Za-z0-9]{2,5}\s*>>")
WS = re.compile(r"\s+")
MIN_BODY_CHARS = 20
THRESHOLD = 90


def normalize_subject(subject: str) -> str:
    return WS.sub(" ", SUBJECT_PREFIX.sub("", subject or "")).strip().lower()


def primary_body(body: str) -> str:
    m = FORWARD_MARKER.search(body)
    kept = body[: m.start()] if m else body
    kept = "\n".join(line for line in kept.splitlines() if not line.lstrip().startswith(">"))
    return WS.sub(" ", kept).strip()


@dataclass
class Email:
    sender: str
    date_key: str
    date_sort: str
    norm_subject: str
    body: str
    has_cc: bool
    has_to: bool
    recipient_count: int
    key: tuple = ()


@dataclass
class Profile:
    mailbox: str
    role: str
    raw: int = 0
    unreadable: int = 0
    unique: dict[tuple, Email] = field(default_factory=dict)


def read_email(path: str) -> Email | None:
    try:
        with open(path, "rb") as f:
            msg = email.message_from_bytes(f.read(), policy=compat32)
    except Exception:
        return None
    payload = msg.get_payload()
    if isinstance(payload, list):
        payload = "\n".join(str(p.get_payload()) for p in payload)
    body = str(payload or "")
    raw_date = str(msg.get("Date", "") or "")
    try:
        dt = parsedate_to_datetime(raw_date)
        date_key = date_sort = dt.astimezone(tz=None).isoformat() if dt.tzinfo else dt.isoformat()
    except Exception:
        date_key, date_sort = raw_date, raw_date
    to = getaddresses([str(v) for v in msg.get_all("To", [])])
    cc = getaddresses([str(v) for v in msg.get_all("Cc", [])])
    return Email(
        sender=str(msg.get("From", "") or "").strip().lower(),
        date_key=date_key,
        date_sort=date_sort,
        norm_subject=normalize_subject(str(msg.get("Subject", "") or "")),
        body=body,
        has_cc=any(addr for _, addr in cc),
        has_to=any(addr for _, addr in to),
        recipient_count=sum(1 for _, a in to + cc if a),
        key=shared_copy_key(msg.get("From"), msg.get("Date"), msg.get("Subject"), body),
    )


def copy_key(e: Email) -> tuple:
    return e.key


def profile_mailbox(maildir: Path, mailbox: str, role: str) -> Profile:
    prof = Profile(mailbox=mailbox, role=role)
    for dirpath, dirnames, filenames in os.walk(maildir / mailbox):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            prof.raw += 1
            e = read_email(os.path.join(dirpath, name))
            if e is None:
                prof.unreadable += 1
                continue
            prof.unique.setdefault(copy_key(e), e)
    return prof


def fuzzy_resends(emails: list[Email]) -> tuple[int, int]:
    """Return (re-send candidates, emails >= THRESHOLD vs their group anchor)."""
    blocks: dict[tuple, list[Email]] = defaultdict(list)
    for e in emails:
        if e.norm_subject:
            blocks[(e.sender, e.norm_subject)].append(e)
    candidates = flagged = 0
    for block in blocks.values():
        if len({e.date_key for e in block}) < 2:
            continue
        candidates += len(block)
        anchors: list[str] = []
        for e in sorted(block, key=lambda x: x.date_sort):
            body = primary_body(e.body)
            if len(body) < MIN_BODY_CHARS:
                continue
            if any(fuzz.ratio(body, a) >= THRESHOLD for a in anchors):
                flagged += 1
            else:
                anchors.append(body)
    return candidates, flagged


def metrics(prof: Profile) -> dict:
    emails = list(prof.unique.values())
    n = len(emails) or 1
    subj_counts: dict[str, int] = defaultdict(int)
    for e in emails:
        if e.norm_subject:
            subj_counts[e.norm_subject] += 1
    candidates, flagged = fuzzy_resends(emails)
    return {
        "mailbox": prof.mailbox,
        "role": prof.role,
        "raw": prof.raw,
        "unique": len(emails),
        "copies_pct": round(100 * (1 - len(emails) / prof.raw), 1) if prof.raw else 0.0,
        "cc_pct": round(100 * sum(e.has_cc for e in emails) / n, 1),
        "fwd_pct": round(100 * sum(bool(FORWARD_MARKER.search(e.body)) for e in emails) / n, 1),
        "quoted_pct": round(100 * sum(bool(QUOTED_LINE.search(e.body)) for e in emails) / n, 1),
        "att_refs": sum(len(ATTACHMENT_REF.findall(e.body)) for e in emails),
        "shared_subj": sum(1 for e in emails if e.norm_subject and subj_counts[e.norm_subject] > 1),
        "resend_cand": candidates,
        "fuzzy90": flagged,
        "no_to_pct": round(100 * sum(not e.has_to for e in emails) / n, 1),
        "big_list_pct": round(100 * sum(e.recipient_count >= 10 for e in emails) / n, 1),
        "unreadable": prof.unreadable,
    }


COLUMNS = [
    ("mailbox", "mailbox", 12), ("role", "role", 10), ("raw", "raw", 7),
    ("unique", "unique", 7), ("copies_pct", "copy%", 6), ("cc_pct", "cc%", 6),
    ("fwd_pct", "fwd%", 6), ("quoted_pct", ">%", 6), ("att_refs", "<<att>>", 8),
    ("shared_subj", "shrSubj", 8), ("resend_cand", "resend?", 8), ("fuzzy90", "fz>=90", 7),
    ("no_to_pct", "noTo%", 6), ("big_list_pct", "10+rc%", 7),
]


def format_table(rows: list[dict]) -> str:
    def fmt(v):
        return f"{v:,}" if isinstance(v, int) else str(v)

    head = " ".join(f"{label:>{w}}" if i > 1 else f"{label:<{w}}"
                    for i, (_, label, w) in enumerate(COLUMNS))
    lines = [head]
    for r in rows:
        lines.append(" ".join(f"{fmt(r[k]):>{w}}" if i > 1 else f"{fmt(r[k]):<{w}}"
                              for i, (k, _, w) in enumerate(COLUMNS)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile candidate Enron mailboxes.")
    parser.add_argument("--maildir", type=Path, default=Path("data/maildir"))
    parser.add_argument("--mailboxes", default=",".join(CANDIDATES))
    parser.add_argument("--combo", default=None, help="comma list: report union size after cross-mailbox collapse")
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args(argv)

    names = [m.strip() for m in args.mailboxes.split(",") if m.strip()]
    profiles = {m: profile_mailbox(args.maildir, m, CANDIDATES.get(m, "?")) for m in names}
    rows = [metrics(p) for p in profiles.values()]
    print(format_table(rows))

    if args.combo:
        combo = [m.strip() for m in args.combo.split(",")]
        union: dict[tuple, Email] = {}
        for m in combo:
            union.update(profiles[m].unique)
        raw = sum(profiles[m].raw for m in combo)
        per_box = sum(len(profiles[m].unique) for m in combo)
        print(f"\nCombo {combo}: raw {raw:,} | sum of per-mailbox unique {per_box:,} "
              f"| unique after cross-mailbox collapse {len(union):,}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
