"""Extraction unit tests (string inputs) for every failure path and the never-raise guarantee."""
import pytest

from pipeline import models
from pipeline.extract import extract_file, extract_text

GOOD = (
    "Message-ID: <1.x@thyme>\r\n"
    "Date: Mon, 14 May 2001 16:39:00 -0700 (PDT)\r\n"
    "From: Phillip.Allen@enron.com\r\n"
    "To: tim.belden@enron.com, \r\n\tjohn.lavorato@enron.com\r\n"
    "Subject: Re: Forecast\r\n"
    "Cc: a@enron.com\r\n"
    "X-From: Phillip K Allen\r\n"
    "X-cc: \r\n"
    "\r\n"
    "Here is our forecast.\n <<forecast.xls>>\n"
)


def test_good_email():
    r = extract_text(GOOD, "maildir/allen-p/sent/1.")
    assert isinstance(r, models.EmailRecord)
    assert r.message_id == "<1.x@thyme>"
    assert r.date == "2001-05-14T23:39:00Z"
    assert r.from_address == "phillip.allen@enron.com"
    assert r.to_addresses == ["tim.belden@enron.com", "john.lavorato@enron.com"]
    assert r.cc_addresses == ["a@enron.com"] and r.bcc_addresses is None
    assert r.subject == "Re: Forecast" and r.normalized_subject == "forecast"
    assert r.x_from == "Phillip K Allen" and r.x_cc is None
    assert r.body == "Here is our forecast.\n <<forecast.xls>>"
    assert r.has_attachment and r.attachments == ["forecast.xls"]


@pytest.mark.parametrize("drop,reason", [
    ("Message-ID", models.MISSING_MESSAGE_ID),
    ("Date", models.MISSING_DATE),
    ("From", models.MISSING_FROM),
    ("To", models.MISSING_TO),
    ("Subject", models.MISSING_SUBJECT),
])
def test_missing_mandatory_header(drop, reason):
    lines = GOOD.split("\r\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(drop + ":"))
    end = start + 1
    while lines[end].startswith("\t"):
        end += 1
    text = "\r\n".join(lines[:start] + lines[end:])
    r = extract_text(text, "maildir/x/1.")
    assert isinstance(r, models.ParseFailure) and r.reason == reason


def test_unparseable_date():
    r = extract_text(GOOD.replace("Mon, 14 May 2001 16:39:00 -0700 (PDT)", "sometime in May"), "f")
    assert r.reason == models.UNPARSEABLE_DATE and "sometime in May" in r.detail


def test_to_with_no_address():
    r = extract_text(GOOD.replace("To: tim.belden@enron.com, \r\n\tjohn.lavorato@enron.com",
                                  "To: undisclosed-recipients:;"), "f")
    assert r.reason == models.MISSING_TO and "no address" in r.detail


def test_empty_subject_is_allowed():
    r = extract_text(GOOD.replace("Subject: Re: Forecast", "Subject: "), "f")
    assert isinstance(r, models.EmailRecord) and r.subject == ""


def test_empty_body_is_allowed():
    head = GOOD.split("\r\n\r\n")[0]
    r = extract_text(head + "\r\n\r\n", "f")
    assert isinstance(r, models.EmailRecord) and r.body == ""


def test_unreadable_file(tmp_path):
    r = extract_file(tmp_path / "nope.", "maildir/x/nope.")
    assert r.reason == models.UNREADABLE


def test_garbage_bytes_never_raise(tmp_path):
    p = tmp_path / "1."
    p.write_bytes(b"\x00\xff\xfe garbage \x81\r\n\r\n\x00")
    r = extract_file(p, "maildir/x/1.")
    assert isinstance(r, models.ParseFailure)


def test_unexpected_exception_becomes_failure(tmp_path, monkeypatch):
    p = tmp_path / "1."
    p.write_text(GOOD)
    monkeypatch.setattr("pipeline.extract.parse_message", lambda t: 1 / 0)
    r = extract_file(p, "maildir/x/1.")
    assert r.reason == models.PARSE_ERROR and "ZeroDivisionError" in r.detail
