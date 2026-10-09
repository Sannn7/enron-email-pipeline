"""NER bonus: storage/idempotency with a fake model (always run), real spaCy checks (skip if not installed)."""
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.db import EmailStore, connect, init_schema
from pipeline.entities import clean_for_ner, extract, run_ner
from pipeline.models import EmailRecord

FIXTURES = Path(__file__).parent / "fixtures"


class FakeNLP:
    """Tags every capitalised word as ORG and every 4-digit number as DATE."""

    def pipe(self, texts, batch_size=64):
        import re
        for t in texts:
            ents = [SimpleNamespace(text=m.group(), label_="DATE" if m.group().isdigit() else "ORG",
                                    start_char=m.start(), end_char=m.end())
                    for m in re.finditer(r"\b(?:[A-Z][a-z]+|\d{4})\b", t)]
            ents.append(SimpleNamespace(text="x", label_="ORG", start_char=0, end_char=1))       # too short
            ents.append(SimpleNamespace(text="Monday", label_="EVENT", start_char=0, end_char=6))  # label dropped
            yield SimpleNamespace(ents=ents)


def rec(n, body, fwd=None, quoted=None):
    return EmailRecord(message_id=f"<{n}@x>", date="2001-01-01T00:00:00Z", from_address="a@x.com",
                       to_addresses=["b@x.com"], subject="s", body=body, source_file=f"maildir/a/inbox/{n}.",
                       normalized_subject="s", body_hash=f"h{n}", copy_key=f"k{n}",
                       forwarded_content=fwd, quoted_content=quoted)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    EmailStore(c).insert_records([
        rec(1, "Enron met Calpine in 2001", fwd="---- Forwarded by Dynegy", quoted="> Reliant said"),
        rec(2, "no entities here"),
        rec(3, "Copy of Enron 2001"),
    ])
    c.execute("UPDATE emails SET is_copy = 1 WHERE message_id = '<3@x>'")
    yield c
    c.close()


def rows(conn):
    return [tuple(r) for r in conn.execute("SELECT e.message_id, n.text, n.label, n.source FROM entities n "
                                           "JOIN emails e ON e.id = n.email_id ORDER BY 1, 4, n.start_char")]


def test_clean_for_ner_removes_qp_keeps_lines():
    assert clean_for_ner("Sorry=20for=\n the delay\r\nNew line =3D x") == "Sorry for the delay\nNew line = x"
    assert clean_for_ner(None) == "" and len(clean_for_ner("a" * 20_000)) == 10_000


class OneEntityNLP:
    """Returns the whole input text as a single entity of the given label."""

    def __init__(self, label):
        self.label = label

    def pipe(self, texts, batch_size=64):
        for t in texts:
            yield SimpleNamespace(ents=[SimpleNamespace(text=t, label_=self.label, start_char=0, end_char=len(t))])


def test_list_lines_are_split_into_separate_entities():
    text = "CMS Marketing, Services and Trading Company\nCalpine Energy Services"
    (ents,) = extract(OneEntityNLP("ORG"), [text])
    assert [e[0] for e in ents] == ["CMS Marketing, Services and Trading Company", "Calpine Energy Services"]
    for t, _, s, e in ents:
        assert text[s:e] == t                                   # offsets point at each piece


def test_wrapped_name_is_kept_whole():
    (ents,) = extract(OneEntityNLP("PERSON"), ["Kenneth\nLay"])
    assert ents == [("Kenneth Lay", "PERSON", 0, 11)]
    (ents,) = extract(OneEntityNLP("ORG"), ["Enron North\nAmerica"])   # one 1-word piece -> no split
    assert [e[0] for e in ents] == ["Enron North America"]


def test_split_skips_blank_lines():
    (ents,) = extract(OneEntityNLP("ORG"), ["Aquila Energy Marketing\n\n  BP Energy Company "])
    assert [e[0] for e in ents] == ["Aquila Energy Marketing", "BP Energy Company"]


def test_sources_labels_and_copies_skipped(conn):
    s = run_ner(conn, nlp=FakeNLP())
    got = rows(conn)
    assert ("<1@x>", "Enron", "ORG", "body") in got
    assert ("<1@x>", "2001", "DATE", "body") in got
    assert ("<1@x>", "Dynegy", "ORG", "forwarded") in got
    assert ("<1@x>", "Reliant", "ORG", "quoted") in got
    assert all(r[0] != "<3@x>" for r in got)                    # is_copy rows are not processed
    assert all(r[2] in ("PERSON", "ORG", "DATE", "GPE") and len(r[1]) >= 2 for r in got)
    assert s.emails == 2 and s.entities == len(got)
    assert s.by_source["forwarded"] == 2 and s.by_source["quoted"] == 1   # "Forwarded", "Dynegy" / "Reliant"


def test_rerun_creates_no_duplicates(conn):
    run_ner(conn, nlp=FakeNLP())
    first = rows(conn)
    run_ner(conn, nlp=FakeNLP())
    run_ner(conn, nlp=FakeNLP(), limit=1)
    assert rows(conn) == first


def test_schema_constraints(conn):
    run_ner(conn, nlp=FakeNLP())
    eid = conn.execute("SELECT id FROM emails LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO entities (email_id, text, label, source, start_char, end_char) "
                     "VALUES (?, 'x', 'EVENT', 'body', 0, 1)", (eid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO entities (email_id, text, label, source, start_char, end_char) "
                     "VALUES (?, 'x', 'ORG', 'subject', 0, 1)", (eid,))


def test_ner_failure_does_not_stop_core_pipeline(tmp_path, capsys, monkeypatch):
    import main as main_module
    import pipeline.entities

    def boom(*a, **k):
        raise ImportError("No module named 'spacy'")
    monkeypatch.setattr(pipeline.entities, "load_model", boom)
    maildir = tmp_path / "maildir"
    shutil.copytree(FIXTURES / "real" / "maildir", maildir)
    out = tmp_path / "out"
    assert main_module.main(["--maildir", str(maildir), "--mailboxes", "all", "--db", str(tmp_path / "t.db"),
                             "--output-dir", str(out), "--error-log", str(tmp_path / "e.txt"),
                             "--report", str(tmp_path / "r.csv"), "--ner"]) == 0
    text = capsys.readouterr().out
    assert "NER skipped (ImportError" in text and "core pipeline continues" in text
    assert (out / "replies").exists() and (tmp_path / "r.csv").exists()
    assert json.loads((out / "run_summary.json").read_text())["ner"]["error"].startswith("ImportError")


# ---- real spaCy model -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def nlp():
    spacy = pytest.importorskip("spacy")
    try:
        from pipeline.entities import load_model
        return load_model()
    except OSError:
        pytest.skip("en_core_web_sm not installed")


def found(ents, label, expected):
    texts = [t.lower() for t, l, _, _ in ents if l == label]
    return any(expected.lower() in t or t in expected.lower() for t in texts if len(t) > 2)


def test_model_keeps_only_ner_components(nlp):
    assert set(nlp.pipe_names) <= {"tok2vec", "ner"} and "ner" in nlp.pipe_names


def test_small_samples(nlp):
    ents = extract(nlp, ["Kenneth Lay met FERC commissioners in Houston on May 14, 2001.",
                         "Jeff Skilling will call Calpine Corporation in California next week."])
    assert found(ents[0], "PERSON", "Kenneth Lay")
    assert found(ents[0], "GPE", "Houston")
    assert found(ents[0], "DATE", "May 14, 2001")
    assert found(ents[1], "PERSON", "Jeff Skilling")
    assert found(ents[1], "GPE", "California")
    assert found(ents[1], "ORG", "Calpine Corporation")


@pytest.mark.parametrize("fixture", ["F15a_ner_orgs", "F15b_ner_people_places"])
def test_ner_fixtures_find_expected_entities(nlp, fixture):
    exp = json.loads((FIXTURES / "expected" / f"{fixture}.json").read_text())
    c = connect(":memory:")
    init_schema(c)
    from pipeline.extract import extract_file
    src = exp["fields"]["source_file"]
    EmailStore(c).insert_records([extract_file(FIXTURES / "real" / src, src)])
    run_ner(c, nlp=nlp)
    ents = [(t, l, 0, 0) for t, l in c.execute("SELECT text, label FROM entities")]
    missing = [f"{label}:{name}" for label, names in exp["ner_expect_at_least"].items()
               for name in names if not found(ents, label, name)]
    assert not missing, f"{fixture} missing {missing}"
