"""Date header -> UTC (Plan step 6)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_tz

# Zones parsedate_tz does not know. (It already knows UT/UTC/GMT/Z and
# EST/EDT/CST/CDT/MST/MDT/PST/PDT.) Hours offset from UTC.
EXTRA_ZONES = {
    "AST": -4, "ADT": -3, "AKST": -9, "AKDT": -8, "HST": -10,
    "BST": 1, "CET": 1, "CEST": 2, "EET": 2, "EEST": 3, "IST": 5.5, "JST": 9,
}
COMMENT = re.compile(r"\([^()]*\)")


def parse_date(raw: str | None) -> datetime | None:
    """Parse an RFC 2822-ish date into an aware UTC datetime; None if unparseable.

    The trailing "(PST)" comment is ignored when a numeric offset is present.
    A bare zone abbreviation is resolved via parsedate_tz or EXTRA_ZONES.
    A date with no zone information at all is treated as UTC.
    """
    if not raw or not raw.strip():
        return None
    text = COMMENT.sub("", raw).strip()
    parts = parsedate_tz(text)
    if parts is None:
        return None
    # parsedate_tz silently returns offset 0 for zones it does not know, so
    # check our own table first.
    last = text.split()[-1].upper()
    if last in EXTRA_ZONES:
        offset = int(EXTRA_ZONES[last] * 3600)
    else:
        offset = parts[9] or 0
    try:
        local = datetime(*parts[:6])
    except ValueError:
        return None
    return (local - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)


def to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
