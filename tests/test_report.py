import csv

from pipeline.copies import collapse_copies
from pipeline.db import EmailStore, connect, init_schema
from pipeline.dedup import detect_duplicates
from pipeline.models import EmailRecord
from pipeline.report import COLUMNS, SPEC_COLUMNS, write_report

BODY = "The quarterly forecast numbers are attached for review."


def rec(n, date, body=BODY, sender="a@enron.com"):
    return EmailRecord(message_id=f"<{n}@x>", date=date, from_address=sender, to_addresses=["b@x.com"],
                       subject=f"RE: Forecast {'' if n % 2 else ''}".strip(), body=body,
                       source_file=f"maildir/a/inbox/{n}.", normalized_subject="forecast",
                       body_hash=f"h{n}", copy_key=f"k{n}")


def build(tmp_path):
    conn = connect(":memory:")
    init_schema(conn)
    EmailStore(conn).insert_records([
        rec(1, "2001-01-01T00:00:00Z"), rec(2, "2001-01-03T00:00:00Z"), rec(3, "2001-01-02T00:00:00Z"),
        rec(4, "2001-01-01T00:00:00Z", body="Completely different text about lunch plans today."),
    ])
    collapse_copies(conn)
    detect_duplicates(conn)
    path = tmp_path / "duplicates_report.csv"
    n = write_report(conn, path)
    return conn, path, n


def test_columns_exact_spec_order(tmp_path):
    _, path, _ = build(tmp_path)
    header = next(csv.reader(path.open()))
    assert header[:7] == SPEC_COLUMNS == ["duplicate_message_id", "original_message_id", "subject", "from_address",
                                          "duplicate_date", "original_date", "similarity_score"]
    assert header == COLUMNS


def test_report_matches_database_flags(tmp_path):
    conn, path, n = build(tmp_path)
    rows = list(csv.DictReader(path.open()))
    flagged = conn.execute("SELECT message_id, duplicate_of, date, similarity_score, source_file "
                           "FROM emails WHERE is_duplicate = 1 ORDER BY date").fetchall()
    assert n == len(rows) == len(flagged) == 2
    by_id = {r["duplicate_message_id"]: r for r in rows}
    for mid, orig, date, score, source in flagged:
        r = by_id[mid]
        assert r["original_message_id"] == orig == "<1@x>"
        assert r["duplicate_date"] == date and r["original_date"] == "2001-01-01T00:00:00Z"
        assert float(r["similarity_score"]) == score == 100.0
        assert r["duplicate_source_file"] == source and r["original_source_file"] == "maildir/a/inbox/1."
    assert "<1@x>" not in by_id and "<4@x>" not in by_id


def test_empty_report_has_header_only(tmp_path):
    conn = connect(":memory:")
    init_schema(conn)
    path = tmp_path / "r.csv"
    assert write_report(conn, path) == 0
    assert path.read_text().strip() == ",".join(COLUMNS)
