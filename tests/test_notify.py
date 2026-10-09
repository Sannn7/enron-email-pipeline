import csv
import email
import json
from datetime import datetime, timezone
from email.policy import default as default_policy

import pytest

from pipeline.db import EmailStore, connect, init_schema
from pipeline.models import EmailRecord
from pipeline.notify.eml_writer import write_all
from pipeline.notify.run import run_notify
from pipeline.notify.sender import (SEND_LOG_COLUMNS, all_notifications, pending_targets, send_notifications,
                                    sync_send_log)
from pipeline.notify.template import build_notification, notice_subject, reply_filename

NOW = datetime(2026, 10, 9, 18, 0, 0, tzinfo=timezone.utc)

SPEC_BODY = """\
This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  <dup@x>
    Date Sent:   2001-05-14T23:39:00Z
    Subject:     RE: Forecast

  Original Email on Record:
    Message-ID:  <orig@x>
    Date Sent:   2001-05-13T10:00:00Z

  Similarity Score: 96.43%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
"""

DUP = {"message_id": "<dup@x>", "date": "2001-05-14T23:39:00Z", "subject": "RE: Forecast",
       "from_address": "phillip.allen@enron.com", "similarity_score": 96.43}
ORIG = {"message_id": "<orig@x>", "date": "2001-05-13T10:00:00Z", "subject": "Forecast",
        "from_address": "phillip.allen@enron.com"}


# ---- template -------------------------------------------------------------------------------

@pytest.mark.parametrize("original,expected", [
    ("Forecast", "[Duplicate Notice] Re: Forecast"),
    ("RE: Forecast", "[Duplicate Notice] RE: Forecast"),
    ("re:Forecast", "[Duplicate Notice] re:Forecast"),
    ("  Re: Re: Lunch ", "[Duplicate Notice] Re: Re: Lunch"),   # kept as written, never an extra Re:
    ("Fwd: Forecast", "[Duplicate Notice] Re: Fwd: Forecast"),
    ("Reorg update", "[Duplicate Notice] Re: Reorg update"),     # 'Re' without a colon is not a prefix
    ("", "[Duplicate Notice] Re: (no subject)"),
    (None, "[Duplicate Notice] Re: (no subject)"),
])
def test_subject_never_re_re(original, expected):
    assert notice_subject(original) == expected


def test_body_matches_spec_template_exactly():
    n = build_notification(DUP, ORIG)
    assert n.body == SPEC_BODY
    assert n.to == "phillip.allen@enron.com" and n.references == "<dup@x>"
    assert n.subject == "[Duplicate Notice] Re: Forecast"   # from the ORIGINAL's subject


def test_score_formatting():
    assert "Similarity Score: 100.00%" in build_notification({**DUP, "similarity_score": 100}, ORIG).body


def test_reply_filename_stable_hash():
    assert reply_filename("<dup@x>") == reply_filename("<dup@x>")
    assert reply_filename("<dup@x>") != reply_filename("<dup2@x>")
    assert reply_filename("<dup@x>").startswith("reply_") and len(reply_filename("<dup@x>")) == len("reply_") + 16 + 4


# ---- database fixtures ------------------------------------------------------------------------

def rec(mid, date, sender="a@enron.com", subj="Forecast", source=None):
    return EmailRecord(message_id=mid, date=date, from_address=sender, to_addresses=["b@x.com"], subject=subj,
                       body="The forecast numbers are attached for your review.",
                       source_file=source or f"maildir/a/inbox/{mid.strip('<>@x')}.",
                       normalized_subject="forecast", body_hash=mid, copy_key=mid)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    EmailStore(c).insert_records([
        rec("<o1@x>", "2001-01-01T00:00:00Z"), rec("<d1@x>", "2001-01-02T00:00:00Z"),
        rec("<d2@x>", "2001-01-05T00:00:00Z"),                               # latest of group 1
        rec("<o2@x>", "2001-02-01T00:00:00Z", sender="c@enron.com", subj="RE: Gas"),
        rec("<d3@x>", "2001-02-02T00:00:00Z", sender="c@enron.com", subj="RE: Gas"),  # only dup of group 2
        rec("<o3@x>", "2001-03-01T00:00:00Z", sender="e@enron.com"),
        rec("<d4@x>", "2001-03-02T00:00:00Z", sender="e@enron.com"),         # group 3
    ])
    with c:
        for dup, orig, score in [("<d1@x>", "<o1@x>", 100.0), ("<d2@x>", "<o1@x>", 95.5),
                                 ("<d3@x>", "<o2@x>", 91.0), ("<d4@x>", "<o3@x>", 99.0)]:
            c.execute("UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = ? "
                      "WHERE message_id = ?", (orig, score, dup))
    yield c
    c.close()


class FakeClient:
    """Stands in for the MCP server: records calls, can fail on chosen message ids."""

    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], set(fail_on)

    def send_email(self, to, subject, body, references="", original_to=""):
        self.calls.append({"to": to, "subject": subject, "body": body, "references": references,
                           "original_to": original_to})
        if references in self.fail_on:
            raise RuntimeError("SMTP 535 auth failed")
        return "sent"


def send(conn, tmp_path, client, answer="y", max_send=10, delay=2.0, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    out = []
    r = send_notifications(conn, pending_targets(conn), client, "me@test.com", max_send, delay,
                           tmp_path / "send_log.csv", input_fn=lambda _: answer, sleep_fn=sleeps.append,
                           now_fn=lambda: "2026-10-09T18:00:00Z", out=out.append)
    return r, out


def log_rows(tmp_path):
    p = tmp_path / "send_log.csv"
    return list(csv.DictReader(p.open())) if p.exists() else []


# ---- target selection ---------------------------------------------------------------------

def test_all_notifications_one_per_flagged(conn):
    assert sorted(n.duplicate_message_id for n in all_notifications(conn)) == ["<d1@x>", "<d2@x>", "<d3@x>", "<d4@x>"]


def test_pending_targets_latest_per_group_only(conn):
    assert sorted(n.duplicate_message_id for n in pending_targets(conn)) == ["<d2@x>", "<d3@x>", "<d4@x>"]


def test_notified_group_is_never_targeted_again(conn):
    conn.execute("UPDATE emails SET notification_sent = 1 WHERE message_id = '<d2@x>'")
    ids = [n.duplicate_message_id for n in pending_targets(conn)]
    assert "<d2@x>" not in ids and "<d1@x>" not in ids


# ---- sender ----------------------------------------------------------------------------------

def test_cap_delay_redirect_log_and_flags(conn, tmp_path):
    client, sleeps = FakeClient(), []
    r, out = send(conn, tmp_path, client, max_send=2, delay=2.0, sleeps=sleeps)
    assert (r.pending, r.attempted, r.sent, r.failed, r.aborted) == (3, 2, 2, 0, False)
    assert len(client.calls) == 2
    assert all(c["to"] == "me@test.com" for c in client.calls)                    # redirected
    assert client.calls[0]["original_to"] in ("a@enron.com", "c@enron.com", "e@enron.com")
    assert sleeps == [2.0]                                                       # between sends only
    assert any("redirected from" in line for line in out) and any("[y/N]" not in l for l in out)
    rows = log_rows(tmp_path)
    assert list(rows[0].keys())[:6] == SEND_LOG_COLUMNS
    assert [r["status"] for r in rows] == ["sent", "sent"]
    assert {r["message_id_referenced"] for r in rows} == {c["references"] for c in client.calls}
    sent = conn.execute("SELECT message_id, notification_date FROM emails WHERE notification_sent = 1").fetchall()
    assert {m for m, _ in sent} == {c["references"] for c in client.calls}
    assert all(d == "2026-10-09T18:00:00Z" for _, d in sent)


@pytest.mark.parametrize("answer", ["n", "N", "", "no", "maybe"])
def test_abort_sends_nothing(conn, tmp_path, answer):
    client = FakeClient()
    r, out = send(conn, tmp_path, client, answer=answer)
    assert r.aborted and client.calls == [] and log_rows(tmp_path) == []
    assert conn.execute("SELECT COUNT(*) FROM emails WHERE notification_sent = 1").fetchone()[0] == 0


def test_yes_variants_proceed(conn, tmp_path):
    assert send(conn, tmp_path, FakeClient(), answer=" YES ")[0].sent == 3


def test_failed_send_logged_not_marked_and_retried_next_run(conn, tmp_path):
    first = pending_targets(conn)[0].duplicate_message_id
    r, _ = send(conn, tmp_path, FakeClient(fail_on={first}))
    assert (r.sent, r.failed) == (2, 1)
    failed = [x for x in log_rows(tmp_path) if x["status"] == "failed"]
    assert failed[0]["message_id_referenced"] == first and "535" in failed[0]["error_message"]
    # next run: only the failed one is pending again
    assert [n.duplicate_message_id for n in pending_targets(conn)] == [first]


def test_rerun_is_idempotent(conn, tmp_path):
    send(conn, tmp_path, FakeClient())
    client = FakeClient()
    r, out = send(conn, tmp_path, client)
    assert r.pending == 0 and client.calls == [] and len(log_rows(tmp_path)) == 3


def test_redirect_required(conn, tmp_path):
    with pytest.raises(ValueError):
        send_notifications(conn, pending_targets(conn), FakeClient(), "", 10, 0, tmp_path / "l.csv",
                           input_fn=lambda _: "y")


def test_sync_send_log_route_b(conn, tmp_path):
    log = tmp_path / "send_log.csv"
    log.write_text("timestamp,recipient,subject,message_id_referenced,status,error_message\n"
                   "2026-10-09T18:05:00Z,me@test.com,s,<d3@x>,sent,\n"
                   "2026-10-09T18:06:00Z,me@test.com,s,<d4@x>,failed,boom\n")
    assert sync_send_log(conn, log) == 1
    assert sync_send_log(conn, log) == 0     # idempotent
    assert conn.execute("SELECT notification_date FROM emails WHERE message_id = '<d3@x>'").fetchone()[0] == \
        "2026-10-09T18:05:00Z"


# ---- .eml drafts and run_notify --------------------------------------------------------------

def test_eml_files_one_per_flagged_and_stale_removed(conn, tmp_path):
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "reply_stale0000000000.eml").write_text("old")
    assert write_all(all_notifications(conn), replies, NOW) == 4
    files = sorted(p.name for p in replies.glob("*.eml"))
    assert files == sorted(reply_filename(m) for m in ["<d1@x>", "<d2@x>", "<d3@x>", "<d4@x>"])
    msg = email.message_from_bytes((replies / reply_filename("<d3@x>")).read_bytes(), policy=default_policy)
    assert msg["To"] == "c@enron.com"                        # dry-run keeps the real sender
    assert msg["Subject"] == "[Duplicate Notice] RE: Gas"   # no "Re: RE:"
    assert msg["References"] == "<d3@x>"
    assert msg["Date"] == "Fri, 09 Oct 2026 18:00:00 +0000"
    assert "Similarity Score: 91.00%" in msg.get_content()


def test_run_notify_dry_run_sends_nothing(conn, tmp_path, monkeypatch):
    from config import Config
    db = tmp_path / "t.db"
    disk = connect(db)
    conn.backup(disk)
    disk.close()
    cfg = Config(db=db, output_dir=tmp_path / "out")
    client = FakeClient()
    s = run_notify(cfg, client=client, now=NOW, out=lambda *_: None)
    assert s["eml_written"] == 4 and s["pending_live_targets"] == 3 and "live" not in s
    assert client.calls == [] and not cfg.send_log.exists()
    payloads = json.loads((cfg.output_dir / "pending_notifications.json").read_text())
    assert len(payloads) == 3 and all("original_to" in p for p in payloads)


def test_run_notify_live_uses_client(conn, tmp_path):
    from config import Config
    db = tmp_path / "t.db"
    disk = connect(db)
    conn.backup(disk)
    disk.close()
    cfg = Config(db=db, output_dir=tmp_path / "out", send_live=True, redirect_to="me@test.com",
                 max_send=1, send_delay=0)
    client = FakeClient()
    s = run_notify(cfg, input_fn=lambda _: "y", client=client, now=NOW, out=lambda *_: None)
    assert s["live"]["sent"] == 1 and len(client.calls) == 1
    s = run_notify(cfg, input_fn=lambda _: "y", client=client, now=NOW, out=lambda *_: None)
    assert s["pending_live_targets"] == 2
