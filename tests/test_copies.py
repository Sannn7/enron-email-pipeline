import email
from email.policy import compat32
from pathlib import Path

import pytest

import scripts.mailbox_profile as profile
from pipeline.copies import collapse_copies, copy_key, copy_key_digest
from pipeline.db import EmailStore, connect, init_schema
from pipeline.models import EmailRecord

FIXTURES = Path(__file__).parent / "fixtures" / "real" / "maildir"

BASE = ("john.doe@enron.com", "Mon, 14 May 2001 16:39:00 -0700 (PDT)", "Re: Forecast", "Here is\n the forecast.")


def test_same_email_same_key():
    assert copy_key(*BASE) == copy_key(*BASE)


def test_equal_instant_in_other_zone_matches():
    other = (BASE[0], "Mon, 14 May 2001 18:39:00 -0500", BASE[2], BASE[3])
    assert copy_key(*other) == copy_key(*BASE)


def test_whitespace_case_and_prefix_insensitive_parts():
    variant = (" JOHN.DOE@enron.com ", BASE[1], "FW: re:  forecast", "Here is the\r\n\tforecast.  ")
    assert copy_key(*variant) == copy_key(*BASE)


@pytest.mark.parametrize("i,value", [
    (0, "jane@enron.com"),
    (1, "Mon, 14 May 2001 16:40:00 -0700"),
    (2, "Forecast v2"),
    (3, "Here is the new forecast."),
])
def test_any_real_difference_changes_key(i, value):
    changed = list(BASE)
    changed[i] = value
    assert copy_key(*changed) != copy_key(*BASE)


def test_unparseable_date_falls_back_to_raw_string():
    k1 = copy_key(BASE[0], "sometime", BASE[2], BASE[3])
    assert k1[1] == "sometime"
    assert copy_key(BASE[0], None, BASE[2], BASE[3])[1] == ""


def test_profile_script_uses_shared_function():
    path = FIXTURES / "symes-k" / "notes_inbox" / "19."
    e = profile.read_email(str(path))
    msg = email.message_from_bytes(path.read_bytes(), policy=compat32)
    assert profile.copy_key(e) == copy_key(msg["From"], msg["Date"], msg["Subject"], str(msg.get_payload()))
    assert profile.shared_copy_key is copy_key


def rec(mid, source, key, date="2001-05-01T13:57:00Z"):
    return EmailRecord(message_id=mid, date=date, from_address="a@x.com", to_addresses=["b@x.com"],
                       subject="s", body="body text long enough", source_file=source,
                       normalized_subject="s", body_hash="h", copy_key=key)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    EmailStore(c).insert_records([
        rec("<3>", "maildir/a/notes_inbox/19.", "K1"),
        rec("<1>", "maildir/a/all_documents/3747.", "K1"),
        rec("<2>", "maildir/a/discussion_threads/3598.", "K1"),
        rec("<4>", "maildir/a/inbox/1.", "K2"),
    ])
    yield c
    c.close()


def flags(conn):
    return {r[0]: (r[1], r[2]) for r in conn.execute("SELECT message_id, is_copy, copy_of FROM emails")}


def test_collapse_marks_all_but_smallest_source_file(conn):
    s = collapse_copies(conn)
    assert (s.emails, s.unique, s.copies, s.copy_groups) == (4, 2, 2, 1)
    assert flags(conn) == {"<1>": (0, None), "<2>": (1, "<1>"), "<3>": (1, "<1>"), "<4>": (0, None)}


def test_collapse_is_idempotent(conn):
    collapse_copies(conn)
    s = collapse_copies(conn)
    assert s.copies == 2 and flags(conn)["<3>"] == (1, "<1>")


def test_literal_mode_marks_nothing(conn):
    collapse_copies(conn)
    s = collapse_copies(conn, "literal")
    assert (s.unique, s.copies) == (4, 0)
    assert all(v == (0, None) for v in flags(conn).values())


def test_digest_is_stable():
    assert copy_key_digest(copy_key(*BASE)) == copy_key_digest(copy_key(*BASE))
    assert len(copy_key_digest(copy_key(*BASE))) == 40


# ---- timezone-shifted copies -------------------------------------------------------------
from pipeline.copies import collapse_tz_shifted  # noqa: E402


def trec(mid, source, date, body_hash="same", sender="a@x.com", nsubj="s"):
    return EmailRecord(message_id=mid, date=date, from_address=sender, to_addresses=["b@x.com"], subject=nsubj,
                       body="body text long enough", source_file=source, normalized_subject=nsubj,
                       body_hash=body_hash, copy_key=mid)


def tz_run(records):
    c = connect(":memory:")
    init_schema(c)
    EmailStore(c).insert_records(records)
    collapse_copies(c)
    s = collapse_tz_shifted(c)
    rows = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT message_id, is_copy, copy_of, copy_kind FROM emails")}
    return s, rows


def test_tz_shift_marks_later_copy_in_other_folder():
    s, rows = tz_run([trec("<a>", "maildir/f/all_documents/1.", "2001-03-14T11:03:00Z"),
                      trec("<b>", "maildir/f/industrials/35.", "2001-03-14T22:03:00Z")])   # +11h
    assert rows["<a>"] == (0, None, None)
    assert rows["<b>"] == (1, "<a>", "tz_shift")
    assert (s.candidates, s.marked, s.clusters, s.shifts) == (2, 1, 1, {11: 1})


@pytest.mark.parametrize("source_b,date_b,body_b,why", [
    ("maildir/f/all_documents/2.", "2001-03-14T21:03:00Z", "same", "same folder"),
    ("maildir/f/other/2.", "2001-03-15T00:03:00Z", "same", "13 hours"),
    ("maildir/f/other/2.", "2001-03-14T21:33:00Z", "same", "minutes differ (10.5h)"),
    ("maildir/f/other/2.", "2001-03-14T21:03:07Z", "same", "seconds differ"),
    ("maildir/f/other/2.", "2001-03-14T21:03:00Z", "different", "body differs"),
    ("maildir/f/other/2.", "2001-03-14T11:03:00Z", "same", "no shift (0h)"),
])
def test_tz_shift_conditions_all_required(source_b, date_b, body_b, why):
    s, rows = tz_run([trec("<a>", "maildir/f/all_documents/1.", "2001-03-14T11:03:00Z"),
                      trec("<b>", source_b, date_b, body_hash=body_b)])
    assert rows["<b>"][0] == 0, why
    assert s.marked == 0


def test_tz_shift_needs_same_sender_and_subject():
    s, _ = tz_run([trec("<a>", "maildir/f/x/1.", "2001-03-14T11:00:00Z"),
                   trec("<b>", "maildir/f/y/1.", "2001-03-14T21:00:00Z", sender="z@x.com"),
                   trec("<c>", "maildir/f/y/2.", "2001-03-14T21:00:00Z", nsubj="other")])
    assert s.marked == 0


def test_tz_shift_twelve_hours_inclusive_and_reset_by_collapse():
    c = connect(":memory:")
    init_schema(c)
    EmailStore(c).insert_records([trec("<a>", "maildir/f/x/1.", "2001-03-14T00:00:00Z"),
                                  trec("<b>", "maildir/f/y/1.", "2001-03-14T12:00:00Z")])
    collapse_copies(c)
    assert collapse_tz_shifted(c).marked == 1
    collapse_copies(c)   # a fresh collapse clears tz_shift flags (stage is recomputed each run)
    assert c.execute("SELECT COUNT(*) FROM emails WHERE is_copy = 1").fetchone()[0] == 0
