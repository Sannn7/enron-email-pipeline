"""Ingest over the real fixture maildir; also checks sample_queries.sql runs."""
import sqlite3
from pathlib import Path

import pytest

from config import Config
from pipeline.ingest import run_ingest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_MAILDIR = ROOT / "tests" / "fixtures" / "real" / "maildir"
MAILBOXES = sorted(p.name for p in FIXTURE_MAILDIR.iterdir() if p.is_dir())


@pytest.fixture
def cfg(tmp_path):
    return Config(maildir=FIXTURE_MAILDIR, mailboxes=MAILBOXES, db=tmp_path / "t.db",
                  output_dir=tmp_path / "out", error_log=tmp_path / "error_log.txt", batch_size=7)


def test_ingest_fixture_maildir(cfg):
    s = run_ingest(cfg)
    assert s.found == 38
    assert (s.parsed, s.failed) == (36, 2)
    assert s.failure_reasons == {"missing_to": 2}
    assert (s.inserted, s.skipped_existing) == (36, 0)
    conn = sqlite3.connect(cfg.db)
    assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 36
    assert conn.execute("SELECT COUNT(*) FROM parse_failures").fetchone()[0] == 2
    # F01: 30 To + 15 Cc + 15 Bcc
    n = conn.execute("""SELECT r.recipient_type, COUNT(*) FROM email_recipients r JOIN emails e ON e.id = r.email_id
                        WHERE e.source_file = 'maildir/staab-t/inbox/87.' GROUP BY 1 ORDER BY 1""").fetchall()
    assert n == [("bcc", 15), ("cc", 15), ("to", 30)]
    log = cfg.error_log.read_text().splitlines()
    assert len(log) == 3
    assert any("maildir/king-j/personal/5. | missing_to" in line for line in log)
    assert (cfg.output_dir / "extraction_stats.json").exists()


def test_rerun_skips_existing_and_reset_starts_over(cfg):
    run_ingest(cfg)
    s = run_ingest(cfg)
    assert (s.inserted, s.skipped_existing) == (0, 36)
    cfg.reset_db = True
    s = run_ingest(cfg)
    assert (s.inserted, s.skipped_existing) == (36, 0)


def test_sample_queries_run(cfg):
    run_ingest(cfg)
    conn = sqlite3.connect(cfg.db)
    sql = (ROOT / "sample_queries.sql").read_text()
    statements, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf)
            buf = ""
    assert len(statements) >= 3
    for stmt in statements:
        conn.execute(stmt).fetchall()
