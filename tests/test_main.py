"""End-to-end: python main.py on the fixture maildir (real + synthetic), dry-run, twice."""
import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import main as main_module
from pipeline.discovery import discover

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def env(tmp_path):
    maildir = tmp_path / "maildir"
    shutil.copytree(FIXTURES / "real" / "maildir", maildir)
    shutil.copytree(FIXTURES / "synthetic" / "maildir", maildir, dirs_exist_ok=True)
    out = tmp_path / "out"
    argv = ["--maildir", str(maildir), "--mailboxes", "all", "--db", str(tmp_path / "t.db"),
            "--output-dir", str(out), "--error-log", str(tmp_path / "error_log.txt"),
            "--report", str(tmp_path / "duplicates_report.csv")]
    return tmp_path, out, argv


def test_mailboxes_all(tmp_path):
    (tmp_path / "a-b" / "inbox").mkdir(parents=True)
    (tmp_path / "a-b" / "inbox" / "1.").write_text("x")
    (tmp_path / ".hidden").mkdir()
    assert [f.source_file for f in discover(tmp_path, ["all"])] == ["maildir/a-b/inbox/1."]


def test_main_end_to_end_dry_run_twice(env, capsys):
    tmp, out, argv = env
    assert main_module.main(argv) == 0
    text = capsys.readouterr().out
    assert "39 files | parsed 37 | failed 2" in text
    assert "dry-run: nothing sent" in text

    summary = json.loads((out / "run_summary.json").read_text())
    flagged = summary["dedup"]["flagged"]
    assert summary["extraction"]["inserted"] == 37
    assert flagged >= 3                                     # F13r, F13x, F13c at least
    assert len(list((out / "replies").glob("reply_*.eml"))) == flagged
    rows = list(csv.DictReader((tmp / "duplicates_report.csv").open()))
    assert len(rows) == flagged
    assert (tmp / "error_log.txt").read_text().count("missing_to") == 2
    assert not (out / "send_log.csv").exists()

    conn = sqlite3.connect(tmp / "t.db")
    before = conn.execute("SELECT message_id, is_copy, is_duplicate, duplicate_of, similarity_score, "
                          "notification_sent FROM emails ORDER BY message_id").fetchall()
    conn.close()

    # second run: nothing re-inserted, identical flags, still nothing sent
    assert main_module.main(argv) == 0
    text = capsys.readouterr().out
    assert "inserted 0 | already in DB 37" in text
    conn = sqlite3.connect(tmp / "t.db")
    after = conn.execute("SELECT message_id, is_copy, is_duplicate, duplicate_of, similarity_score, "
                         "notification_sent FROM emails ORDER BY message_id").fetchall()
    assert after == before
    assert json.loads((out / "run_summary.json").read_text())["dedup"]["flagged"] == flagged


def test_main_sync_send_log_marks_once(env, capsys):
    tmp, out, argv = env
    main_module.main(argv)
    conn = sqlite3.connect(tmp / "t.db")
    dup = conn.execute("SELECT message_id FROM emails WHERE is_duplicate = 1 LIMIT 1").fetchone()[0]
    conn.close()
    (out / "send_log.csv").write_text("timestamp,recipient,subject,message_id_referenced,status,error_message\n"
                                      f"2026-10-09T18:00:00Z,me@test.com,s,{dup},sent,\n")
    main_module.main(argv + ["--sync-send-log"])
    assert "synced 1 send(s)" in capsys.readouterr().out
    main_module.main(argv + ["--sync-send-log"])
    assert "synced 0 send(s)" in capsys.readouterr().out
