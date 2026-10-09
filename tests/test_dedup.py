import string

import pytest

from pipeline.copies import collapse_copies
from pipeline.db import EmailStore, connect, init_schema
from pipeline.dedup import (EXCLUDED_NO_FORWARD, EXCLUDED_SHORT_FORWARD, comparison_text, detect_duplicates,
                            is_bogus_date, similarity)
from pipeline.models import EmailRecord

BASE = (string.ascii_lowercase * 4)[:100]  # 100 chars, no whitespace


def mutate(text: str, positions) -> str:
    """Substitute characters; for equal-length strings fuzz.ratio = 100 * (1 - subs/len)."""
    chars = list(text)
    for p in positions:
        chars[p] = "#" if chars[p] != "#" else "@"
    return "".join(chars)


_n = 0


def rec(body, date, sender="a@enron.com", nsubj="forecast", fwd=None, source=None, key=None):
    global _n
    _n += 1
    return EmailRecord(message_id=f"<{_n}@x>", date=date, from_address=sender, to_addresses=["b@x.com"],
                       subject=nsubj, body=body, source_file=source or f"maildir/a/inbox/{_n:03d}.",
                       normalized_subject=nsubj, body_hash=f"h{_n}", copy_key=key or f"k{_n}",
                       forwarded_content=fwd)


def run(records, threshold=90.0, min_chars=20):
    conn = connect(":memory:")
    init_schema(conn)
    EmailStore(conn).insert_records(records)
    collapse_copies(conn)
    stats = detect_duplicates(conn, threshold, min_chars)
    rows = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT message_id, is_duplicate, duplicate_of, similarity_score FROM emails")}
    return conn, stats, rows


def test_threshold_is_inclusive_at_90():
    a = rec(BASE, "2001-01-01T00:00:00Z")
    b = rec(mutate(BASE, range(10)), "2001-01-02T00:00:00Z")      # 90.0
    c = rec(mutate(BASE, range(50, 61)), "2001-01-03T00:00:00Z")  # 89.0
    _, s, rows = run([a, b, c])
    assert rows[b.message_id] == (1, a.message_id, 90.0)
    assert rows[c.message_id] == (0, None, None)
    assert rows[a.message_id] == (0, None, None)                 # the original is never flagged
    assert (s.groups, s.flagged) == (1, 1)


def test_different_sender_or_subject_never_grouped():
    a = rec(BASE, "2001-01-01T00:00:00Z")
    b = rec(BASE, "2001-01-02T00:00:00Z", sender="z@enron.com")
    c = rec(BASE, "2001-01-03T00:00:00Z", nsubj="other")
    _, s, rows = run([a, b, c])
    assert s.flagged == 0 and s.blocks_compared == 0


def test_anchor_matching_not_chaining():
    a = rec(BASE, "2001-01-01T00:00:00Z")
    b = rec(mutate(BASE, range(6)), "2001-01-02T00:00:00Z")          # 94 vs a
    c = rec(mutate(BASE, range(6, 12)), "2001-01-03T00:00:00Z")      # 94 vs a ... make c far from a:
    d = rec(mutate(mutate(BASE, range(6)), range(6, 12)), "2001-01-04T00:00:00Z")  # 88 vs a, 94 vs b
    _, s, rows = run([a, b, c, d])
    assert rows[b.message_id][:2] == (1, a.message_id)
    assert rows[c.message_id][:2] == (1, a.message_id)
    assert rows[d.message_id] == (0, None, None)   # similar to b, but b is not an anchor
    assert s.groups == 1 and s.largest_group == 3


def test_group_of_three_all_point_to_earliest_and_latest_is_flagged():
    a = rec(BASE, "2001-01-05T00:00:00Z")
    b = rec(BASE, "2001-01-01T00:00:00Z")   # earliest -> original
    c = rec(BASE, "2001-01-09T00:00:00Z")
    _, s, rows = run([a, b, c])
    assert rows[b.message_id] == (0, None, None)
    assert rows[a.message_id] == (1, b.message_id, 100.0)
    assert rows[c.message_id] == (1, b.message_id, 100.0)
    assert s.avg_group_size == 3.0


def test_same_timestamp_tie_broken_by_source_file():
    a = rec(BASE, "2001-01-01T00:00:00Z", source="maildir/a/z/1.")
    b = rec(BASE, "2001-01-01T00:00:00Z", source="maildir/a/b/1.")
    _, _, rows = run([a, b])
    assert rows[b.message_id][0] == 0 and rows[a.message_id][:2] == (1, b.message_id)


def test_joins_best_scoring_anchor():
    other = "".join(reversed(BASE))
    a = rec(BASE, "2001-01-01T00:00:00Z")
    b = rec(other, "2001-01-02T00:00:00Z")
    c = rec(mutate(other, range(2)), "2001-01-03T00:00:00Z")   # 98 vs b, far from a
    _, s, rows = run([a, b, c])
    assert rows[c.message_id][:2] == (1, b.message_id) and s.groups == 1


def test_short_body_excluded():
    a = rec("ok thanks", "2001-01-01T00:00:00Z")
    b = rec("ok thanks", "2001-01-02T00:00:00Z")
    _, s, rows = run([a, b])
    assert s.flagged == 0 and s.excluded[EXCLUDED_NO_FORWARD] == 2


def test_forwarded_fallback_used_and_stored_text_untouched():
    fwd = "---- Forwarded by X on 01/01/2001 ----\n" + BASE
    a = rec("", "2001-01-01T00:00:00Z", fwd=fwd)
    b = rec("FYI", "2001-01-15T00:00:00Z", fwd=fwd)
    c = rec("", "2001-01-20T00:00:00Z", fwd="--- short")
    conn, s, rows = run([a, b, c])
    assert rows[b.message_id][:2] == (1, a.message_id)
    assert s.used_forwarded == 2 and s.excluded[EXCLUDED_SHORT_FORWARD] == 1
    stored = conn.execute("SELECT body, forwarded_content FROM emails WHERE message_id = ?", (b.message_id,)).fetchone()
    assert tuple(stored) == ("FYI", fwd)


def test_comparison_text_rules():
    assert comparison_text("x" * 20, None, 20) == ("x" * 20, "primary")
    assert comparison_text("short", "y" * 25, 20) == ("y" * 25, "forwarded")
    assert comparison_text("short", "tiny", 20) == (None, EXCLUDED_SHORT_FORWARD)
    assert comparison_text("", None, 20) == (None, EXCLUDED_NO_FORWARD)
    # quoted-printable cleaned only for comparison
    assert comparison_text("Sorry=20for the=\n delay, see attached file", None, 20)[0] == \
        "Sorry for the delay, see attached file"


def test_bogus_date_never_original():
    bogus = rec(BASE, "1980-01-01T00:00:00Z")
    real = rec(BASE, "2001-03-01T00:00:00Z")
    _, s, rows = run([bogus, real])
    assert rows[real.message_id] == (0, None, None)
    assert rows[bogus.message_id][:2] == (1, real.message_id)
    assert (s.bogus_dates, s.bogus_in_groups, s.bogus_only_groups) == (1, 1, 0)


def test_all_bogus_group_falls_back_to_source_file():
    a = rec(BASE, "1980-01-01T00:00:00Z", source="maildir/a/y/1.")
    b = rec(BASE, "1980-01-01T00:00:00Z", source="maildir/a/b/1.")
    _, s, rows = run([a, b])
    assert rows[a.message_id][:2] == (1, b.message_id) and s.bogus_only_groups == 1


@pytest.mark.parametrize("date,bogus", [("1980-01-01T00:00:00Z", True), ("1996-12-31T23:59:59Z", True),
                                        ("1997-01-01T00:00:00Z", False), ("2002-12-31T23:59:59Z", False),
                                        ("2003-01-01T00:00:00Z", True), ("2043-01-01T00:00:00Z", True)])
def test_is_bogus_date(date, bogus):
    assert is_bogus_date(date) is bogus


def test_copies_are_not_candidates():
    a = rec(BASE, "2001-01-01T00:00:00Z", key="same", source="maildir/a/all_documents/1.")
    b = rec(BASE, "2001-01-01T00:00:00Z", key="same", source="maildir/a/inbox/1.")
    _, s, rows = run([a, b])
    assert s.candidates == 1 and s.flagged == 0


def test_rerun_is_idempotent_and_keeps_notification_flags():
    a, b = rec(BASE, "2001-01-01T00:00:00Z"), rec(BASE, "2001-01-02T00:00:00Z")
    conn, _, _ = run([a, b])
    conn.execute("UPDATE emails SET notification_sent = 1, notification_date = 'x' WHERE message_id = ?",
                 (b.message_id,))
    s = detect_duplicates(conn)
    row = conn.execute("SELECT is_duplicate, duplicate_of, notification_sent FROM emails WHERE message_id = ?",
                       (b.message_id,)).fetchone()
    assert tuple(row) == (1, a.message_id, 1) and s.flagged == 1


def test_similarity_length_prefilter():
    assert similarity("a" * 20, "a" * 100, 90) is None
    assert similarity(BASE, BASE, 90) == 100.0


def test_run_dedup_tz_stage_flag(tmp_path):
    from config import Config
    from pipeline.db import connect as dbconnect
    from pipeline.dedup import run_dedup
    db = tmp_path / "t.db"
    c = dbconnect(db)
    init_schema(c)
    a = rec(BASE, "2001-03-14T11:03:00Z", source="maildir/f/all_documents/1.")
    b = rec(BASE, "2001-03-14T22:03:00Z", source="maildir/f/industrials/1.")
    a.body_hash = b.body_hash = "same"
    EmailStore(c).insert_records([a, b])
    c.close()
    cfg = Config(db=db, output_dir=tmp_path / "out", report=tmp_path / "r.csv")
    _, tz, d, rows = run_dedup(cfg)
    assert tz.marked == 1 and d.flagged == 0 and rows == 0          # merged as a copy, not a duplicate
    cfg.tz_collapse = False
    _, tz, d, rows = run_dedup(cfg)
    assert tz is None and d.flagged == 1 and rows == 1              # literal behaviour: flagged
    cfg.tz_collapse, cfg.dedup_mode = True, "literal"
    _, tz, d, _ = run_dedup(cfg)
    assert tz is None                                               # literal mode skips the stage too
