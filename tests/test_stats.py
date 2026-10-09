import json

from pipeline.models import EmailRecord, ParseFailure
from pipeline.stats import FIELDS, ExtractionStats


def rec(**kw):
    base = dict(message_id="<1@x>", date="2001-01-01T00:00:00Z", from_address="a@x.com",
                to_addresses=["b@x.com"], subject="s", body="hello", source_file="maildir/a/1.")
    base.update(kw)
    return EmailRecord(**base)


def test_counts_and_completeness():
    s = ExtractionStats(found=5)
    s.add_record(rec(cc_addresses=["c@x.com"], has_attachment=True))
    s.add_record(rec(body="", subject=""))                 # empty strings are not "present"
    s.add_record(rec(cc_addresses=[], x_from="A"))          # empty list is not "present"
    s.add_failure(ParseFailure("f1", "missing_to"))
    s.add_failure(ParseFailure("f2", "missing_to"))
    assert (s.found, s.parsed, s.failed) == (5, 3, 2)
    c = s.completeness()
    assert c["message_id"] == 100.0
    assert c["body"] == 66.7 and c["subject"] == 66.7
    assert c["cc_addresses"] == 33.3
    assert c["has_attachment"] == 33.3
    assert c["x_from"] == 33.3
    assert c["bcc_addresses"] == 0.0
    assert set(c) == set(FIELDS)
    assert s.failure_reasons == {"missing_to": 2}


def test_empty_stats():
    s = ExtractionStats()
    assert all(v == 0.0 for v in s.completeness().values())
    assert "files found" in s.format()


def test_json_and_text_output(tmp_path):
    s = ExtractionStats(found=2, inserted=1)
    s.add_record(rec())
    s.add_failure(ParseFailure("f", "missing_to"))
    out = tmp_path / "stats.json"
    s.write_json(out)
    d = json.loads(out.read_text())
    assert d["files_found"] == 2 and d["parsed"] == 1 and d["failed"] == 1
    assert d["failure_reasons"] == {"missing_to": 1}
    assert d["field_completeness_pct"]["to_addresses"] == 100.0
    text = s.format()
    assert "parsed OK                 1  (50.0%)" in text
    assert "missing_to" in text
