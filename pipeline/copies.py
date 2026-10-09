"""Folder-copy key and collapse (Plan step 11).

copy_key() is the single definition shared with scripts/mailbox_profile.py, so
the profile's selection numbers and the pipeline agree. A copy is the same
email stored in several folders/mailboxes: same raw From, same instant, same
normalized subject, same whole body (whitespace collapsed). Each such file has
its own Message-ID, so the UNIQUE message_id constraint does not catch them.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from pipeline.parsing.body import full_body_hash
from pipeline.parsing.headers import normalize_subject

ISO = "%Y-%m-%dT%H:%M:%SZ"


def copy_key(from_header: str | None, date_header: str | None, subject_header: str | None,
             body: str | None) -> tuple[str, str, str, str]:
    """(sender, instant, normalized subject, body hash) from raw header values and the full body.

    - sender: the raw From header, lowercased and trimmed
    - instant: the parsed Date as UTC ISO text (equal instants match across time zones);
      the raw Date string if it cannot be parsed
    - subject: normalize_subject() (Re:/Fw:/Fwd: stripped, whitespace collapsed, lowercased)
    - body: full_body_hash() of the whole body (not just the primary part)
    """
    raw_date = str(date_header or "")
    try:
        dt = parsedate_to_datetime(raw_date)
        instant = dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else dt.isoformat()
    except Exception:
        instant = raw_date
    return (
        str(from_header or "").strip().lower(),
        instant,
        normalize_subject(str(subject_header or "")),
        full_body_hash(str(body or "")),
    )


def copy_key_digest(key: tuple[str, str, str, str]) -> str:
    """Compact form of copy_key() for storage and indexing."""
    return hashlib.sha1("\x1f".join(key).encode("utf-8", "surrogateescape")).hexdigest()


@dataclass
class CopyStats:
    mode: str = "collapse"
    emails: int = 0           # rows in the emails table
    unique: int = 0           # rows left after collapse (canonical + emails with no copies)
    copies: int = 0           # rows marked is_copy = 1
    copy_groups: int = 0      # copy keys with 2+ rows

    def format(self) -> str:
        if self.mode == "literal":
            return f"Copy collapse skipped (--dedup-mode literal): {self.emails:,} emails all eligible"
        return (f"Copy collapse: {self.emails:,} emails -> {self.unique:,} unique "
                f"({self.copies:,} copies in {self.copy_groups:,} groups marked is_copy=1)")


def collapse_copies(conn: sqlite3.Connection, mode: str = "collapse") -> CopyStats:
    """Mark folder copies. Canonical row = lexicographically smallest source_file.

    Idempotent: flags are recomputed from scratch on every run. In literal mode no
    row is marked, so every email takes part in duplicate detection.
    """
    stats = CopyStats(mode=mode)
    with conn:
        conn.execute("UPDATE emails SET is_copy = 0, copy_of = NULL, copy_kind = NULL")
        rows = conn.execute(
            "SELECT id, copy_key, message_id FROM emails ORDER BY copy_key, source_file").fetchall()
        stats.emails = len(rows)
        if mode == "literal":
            stats.unique = len(rows)
            return stats
        updates, prev_key, canonical = [], None, None
        for row_id, key, message_id in rows:
            if key == prev_key:
                updates.append((canonical, row_id))
            else:
                prev_key, canonical = key, message_id
        conn.executemany("UPDATE emails SET is_copy = 1, copy_of = ?, copy_kind = 'folder' WHERE id = ?", updates)
        stats.copies = len(updates)
        stats.unique = stats.emails - stats.copies
        stats.copy_groups = len({c for c, _ in updates})
    return stats


# ---- timezone-shifted copies (separate stage; copy_key is unchanged) --------------------

MAX_SHIFT_HOURS = 12


@dataclass
class TzShiftStats:
    candidates: int = 0       # non-copy rows before this stage
    marked: int = 0           # rows marked is_copy = 1, copy_kind = 'tz_shift'
    clusters: int = 0         # canonical rows that absorbed at least one shifted copy
    shifts: dict = None       # hours -> count

    def format(self) -> str:
        shifts = ", ".join(f"{h}h: {n}" for h, n in sorted((self.shifts or {}).items()))
        return (f"Timezone-shifted copies: {self.candidates:,} -> {self.candidates - self.marked:,} unique "
                f"({self.marked:,} marked in {self.clusters:,} clusters; shifts {shifts or 'none'})")


def _is_tz_shift(anchor: tuple, other: tuple) -> int | None:
    """Whole-hour shift (1..12) between two same-content rows in different folders, else None."""
    a_date, a_folder = anchor
    b_date, b_folder = other
    if a_folder == b_folder or a_date[14:19] != b_date[14:19]:   # minutes:seconds must match
        return None
    delta = (datetime.strptime(b_date, ISO) - datetime.strptime(a_date, ISO)).total_seconds()
    hours, rest = divmod(abs(delta), 3600)
    if rest or not 1 <= hours <= MAX_SHIFT_HOURS:
        return None
    return int(hours)


def collapse_tz_shifted(conn: sqlite3.Connection) -> TzShiftStats:
    """Mark copies whose only difference is a whole-hour timestamp shift (export time zone error).

    Conditions, all required: same from_address, same normalized subject, identical full body
    (same body_hash, i.e. similarity 100), different folders, a shift of a whole number of
    hours between 1 and 12, and identical minutes:seconds. Canonical = earliest row, then
    smallest source_file. Must run right after collapse_copies(), which resets all copy flags.
    """
    stats = TzShiftStats(shifts={})
    rows = conn.execute(
        """SELECT id, message_id, from_address, normalized_subject, body_hash, date, source_file
           FROM emails WHERE is_copy = 0
           ORDER BY from_address, normalized_subject, body_hash, date, source_file""").fetchall()
    stats.candidates = len(rows)
    updates, canonicals = [], set()
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j][2:5] == rows[i][2:5]:
            j += 1
        anchors: list[tuple] = []  # (message_id, date, folder)
        for row_id, mid, _, _, _, date, source in rows[i:j]:
            folder = source.rsplit("/", 1)[0]
            for a_mid, a_date, a_folder in anchors:
                hours = _is_tz_shift((a_date, a_folder), (date, folder))
                if hours:
                    updates.append((a_mid, row_id))
                    canonicals.add(a_mid)
                    stats.shifts[hours] = stats.shifts.get(hours, 0) + 1
                    break
            else:
                anchors.append((mid, date, folder))
        i = j
    with conn:
        conn.executemany("UPDATE emails SET is_copy = 1, copy_of = ?, copy_kind = 'tz_shift' WHERE id = ?", updates)
    stats.marked = len(updates)
    stats.clusters = len(canonicals)
    return stats
