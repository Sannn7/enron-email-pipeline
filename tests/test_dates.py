import pytest

from pipeline.parsing.dates import parse_date, to_iso_utc


@pytest.mark.parametrize("raw,expected", [
    ("Mon, 14 May 2001 16:39:00 -0700 (PDT)", "2001-05-14T23:39:00Z"),
    ("Fri, 14 Dec 2001 12:08:27 -0800 (PST)", "2001-12-14T20:08:27Z"),
    ("Wed, 26 Sep 2001 06:28:33 -0700", "2001-09-26T13:28:33Z"),
    ("Thu, 1 Mar 2001 10:00:00 EST", "2001-03-01T15:00:00Z"),           # bare abbreviation
    ("Thu, 1 Mar 2001 10:00:00 CDT", "2001-03-01T15:00:00Z"),
    ("Thu, 1 Mar 2001 10:00:00 BST", "2001-03-01T09:00:00Z"),           # EXTRA_ZONES
    ("Thu, 1 Mar 2001 10:00:00 GMT", "2001-03-01T10:00:00Z"),
    ("1 Mar 2001 10:00:00 +0530", "2001-03-01T04:30:00Z"),
    ("Mon, 31 Dec 2001 23:30:00 -0800 (PST)", "2002-01-01T07:30:00Z"),  # crosses the year
    ("Thu, 1 Jan 1979 00:00:00 -0800 (PST)", "1979-01-01T08:00:00Z"),   # bogus year kept as-is
    ("Thu, 1 Mar 2001 10:00:00", "2001-03-01T10:00:00Z"),               # no zone -> UTC
])
def test_parse_to_utc(raw, expected):
    assert to_iso_utc(parse_date(raw)) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "not a date", "32 Foo 2001 99:99:99", "Thu, 31 Feb 2001 10:00:00 -0800"])
def test_unparseable_returns_none(raw):
    assert parse_date(raw) is None
