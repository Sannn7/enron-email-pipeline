"""Group-level expectations of the F13* / F14b3 fixtures, run through ingest + collapse + dedup."""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from config import Config
from pipeline.copies import collapse_copies, collapse_tz_shifted
from pipeline.dedup import detect_duplicates
from pipeline.ingest import run_ingest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / "expected" / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dedupfx")
    maildir = tmp / "maildir"
    shutil.copytree(FIXTURES / "real" / "maildir", maildir)
    shutil.copytree(FIXTURES / "synthetic" / "maildir", maildir, dirs_exist_ok=True)
    cfg = Config(maildir=maildir, mailboxes=sorted(p.name for p in maildir.iterdir()),
                 db=tmp / "t.db", output_dir=tmp / "out", error_log=tmp / "err.txt")
    run_ingest(cfg)
    conn = sqlite3.connect(cfg.db)
    collapse_copies(conn)
    collapse_tz_shifted(conn)
    detect_duplicates(conn)
    yield conn
    conn.close()


def row(conn, source):
    r = conn.execute("SELECT message_id, is_copy, copy_of, is_duplicate, duplicate_of, similarity_score "
                     "FROM emails WHERE source_file = ?", (source,)).fetchone()
    assert r is not None, source
    return dict(zip(["message_id", "is_copy", "copy_of", "is_duplicate", "duplicate_of", "score"], r))


@pytest.mark.parametrize("name", ["F13r_synthetic_resend", "F13x_timezone_edge_case", "F13c_forwarded_fallback"])
def test_flagged_pairs(db, name):
    exp = load(name)["expected"]
    orig, dup = row(db, exp["original"]), row(db, exp["flagged"])
    assert orig["is_duplicate"] == 0
    assert dup["is_duplicate"] == 1 and dup["duplicate_of"] == orig["message_id"]
    assert dup["score"] == pytest.approx(exp["measured_similarity"], abs=0.05)


def test_near_miss_not_flagged(db):
    exp = load("F13a_near_miss")
    for m in exp["members"]:
        assert row(db, m["source_file"])["is_duplicate"] == 0


def test_folder_copies(db):
    exp = load("F13b_folder_copies")["expected"]
    canon = row(db, exp["canonical"])
    assert canon["is_copy"] == 0 and canon["message_id"] == exp["copy_of"]
    for c in exp["copies"]:
        r = row(db, c)
        assert r["is_copy"] == 1 and r["copy_of"] == exp["copy_of"] and r["is_duplicate"] == 0
    assert canon["is_duplicate"] == 0


def test_unrelated_template_not_duplicate(db):
    for m in load("F14b3_unrelated_people")["members"]:
        assert row(db, m["source_file"])["is_duplicate"] == 0
