import sqlite3

import pytest

from pipeline.db import EmailStore, connect, init_schema, write_error_log
from pipeline.models import EmailRecord, ParseFailure


def rec(mid="<1@x>", source="maildir/a-b/inbox/1.", **kw):
    base = dict(message_id=mid, date="2001-05-14T23:39:00Z", from_address="a@enron.com",
                to_addresses=["b@enron.com", "c@enron.com"], subject="Re: Hi", body="hello",
                source_file=source, normalized_subject="hi", body_hash="h1")
    base.update(kw)
    return EmailRecord(**base)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    yield c
    c.close()


def names(conn, kind):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def test_schema_tables_and_required_indexes(conn):
    assert {"emails", "addresses", "email_recipients", "attachments", "parse_failures", "threads"} <= names(conn, "table")
    assert {"idx_emails_date", "idx_emails_from_address", "idx_emails_subject"} <= names(conn, "index")


def test_required_columns_and_defaults(conn):
    cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(emails)")}
    for col in ("is_duplicate", "duplicate_of", "notification_sent", "notification_date",
                "similarity_score", "is_copy", "copy_of", "thread_id"):
        assert col in cols
    EmailStore(conn).insert_records([rec()])
    row = conn.execute("SELECT is_duplicate, duplicate_of, notification_sent, notification_date, is_copy "
                       "FROM emails").fetchone()
    assert tuple(row) == (0, None, 0, None, 0)


def test_init_schema_is_idempotent(conn):
    init_schema(conn)
    init_schema(conn)


def test_message_id_unique_on_insert(conn):
    store = EmailStore(conn)
    r1 = store.insert_records([rec(), rec(source="maildir/a-b/inbox/2.")])  # same message_id
    assert (r1.inserted, r1.skipped_existing) == (1, 1)
    r2 = store.insert_records([rec()])                                       # re-run
    assert (r2.inserted, r2.skipped_existing) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO emails (message_id, date, from_address, subject, body, source_file, "
                     "normalized_subject, body_hash) VALUES ('<1@x>', 'd', 'f', 's', 'b', 'other', 'n', 'h')")


def test_recipients_normalized(conn):
    store = EmailStore(conn)
    store.insert_records([
        rec(cc_addresses=["d@enron.com"], bcc_addresses=["d@enron.com"]),
        rec(mid="<2@x>", source="maildir/a-b/inbox/2.", to_addresses=["c@enron.com"]),
    ])
    # c@enron.com appears in two emails but is stored once
    assert conn.execute("SELECT COUNT(*) FROM addresses").fetchone()[0] == 3
    rows = conn.execute("""SELECT e.message_id, r.recipient_type, r.position, a.email
                           FROM email_recipients r JOIN emails e ON e.id = r.email_id
                           JOIN addresses a ON a.id = r.address_id
                           ORDER BY e.message_id, r.recipient_type, r.position""").fetchall()
    assert [tuple(r) for r in rows] == [
        ("<1@x>", "bcc", 0, "d@enron.com"), ("<1@x>", "cc", 0, "d@enron.com"),
        ("<1@x>", "to", 0, "b@enron.com"), ("<1@x>", "to", 1, "c@enron.com"),
        ("<2@x>", "to", 0, "c@enron.com"),
    ]


def test_same_address_twice_in_one_header(conn):
    EmailStore(conn).insert_records([rec(to_addresses=["b@enron.com", "b@enron.com"])])
    assert conn.execute("SELECT COUNT(*) FROM email_recipients").fetchone()[0] == 2


def test_attachments_and_optional_fields(conn):
    EmailStore(conn).insert_records([rec(attachments=["a.doc", "b.xls", "a.doc"], has_attachment=True,
                                         x_from="A B", forwarded_content="fwd", references="<0@x>")])
    assert [r[0] for r in conn.execute("SELECT filename FROM attachments ORDER BY filename")] == ["a.doc", "b.xls"]
    row = conn.execute("SELECT has_attachment, x_from, forwarded_content, references_hdr, body_hash FROM emails").fetchone()
    assert tuple(row) == (1, "A B", "fwd", "<0@x>", "h1")


def test_failures_table_and_error_log(conn, tmp_path):
    store = EmailStore(conn)
    store.insert_failures([ParseFailure("maildir/a/1.", "missing_to", "To header absent"),
                           ParseFailure("maildir/a/2.", "unparseable_date", "Date: 'x'\nmore")])
    store.insert_failures([ParseFailure("maildir/a/1.", "missing_to", "To header absent")])  # re-run
    assert conn.execute("SELECT COUNT(*) FROM parse_failures").fetchone()[0] == 2
    log = tmp_path / "error_log.txt"
    assert write_error_log(conn, log) == 2
    lines = log.read_text().splitlines()
    assert lines[0].startswith("# timestamp")
    assert lines[1].endswith("| maildir/a/1. | missing_to | To header absent")
    assert lines[2].endswith("| maildir/a/2. | unparseable_date | Date: 'x' more")


def test_connect_creates_parent_dir(tmp_path):
    c = connect(tmp_path / "sub" / "x.db")
    init_schema(c)
    c.close()
    assert (tmp_path / "sub" / "x.db").exists()
