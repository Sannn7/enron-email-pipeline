import pytest

from pipeline.parsing.headers import (get_all_headers, get_body, get_header, normalize_subject,
                                      parse_message, unfold)

CRLF_MSG = (
    "Message-ID: <1.x@thyme>\r\n"
    "To: a@enron.com, \r\n\tb@enron.com\r\n"
    "Subject: RE: Weather  - 09.26.01\r\n"
    "X-cc: \r\n"
    "\r\n"
    "Body line 1\n"
    "To: not-a-header@enron.com\n"
    "Subject: also body\n"
)


def test_crlf_header_lf_body_boundary():
    msg = parse_message(CRLF_MSG)
    assert get_header(msg, "To") == "a@enron.com, b@enron.com"
    body = get_body(msg)
    assert body.startswith("Body line 1\n")
    assert "To: not-a-header@enron.com" in body      # body lines are never headers
    assert get_all_headers(msg, "Subject") == ["RE: Weather  - 09.26.01"]


def test_unfold_keeps_internal_whitespace():
    assert unfold("RE: Weather  - 09.26.01") == "RE: Weather  - 09.26.01"
    assert unfold('"Forman (E-mail)"\r\n\t <x@y.com>') == '"Forman (E-mail)" <x@y.com>'


def test_empty_header_is_none_unless_keep_empty():
    msg = parse_message("X-cc: \r\nSubject: \r\n\r\nb")
    assert get_header(msg, "X-cc") is None
    assert get_header(msg, "Subject", keep_empty=True) == ""
    assert get_header(msg, "Missing") is None


def test_repeated_header_first_wins_all_available():
    msg = parse_message("Subject: first\r\nSubject: second\r\nTo: a@x.com\r\nTo: b@x.com\r\n\r\nb")
    assert get_header(msg, "Subject") == "first"
    assert get_all_headers(msg, "To") == ["a@x.com", "b@x.com"]


def test_malformed_header_line_does_not_crash():
    msg = parse_message("Subject: ok\r\nthis line has no colon\r\nTo: a@x.com\r\n\r\nbody")
    assert get_header(msg, "Subject") == "ok"
    assert isinstance(get_body(msg), str)


def test_body_crlf_normalized():
    assert get_body(parse_message("Subject: s\r\n\r\nline1\r\nline2")) == "line1\nline2"


@pytest.mark.parametrize("raw,expected", [
    ("Re: Forecast", "forecast"),
    ("RE: Fw: RE:  Gas   desk ", "gas desk"),
    ("FWD:Re:x", "x"),
    ("AW: Treffen", "aw: treffen"),       # non-English prefixes are not stripped
    ("Re:", ""),
    (None, ""),
    ("Fwd: Re: Re: Lunch", "lunch"),
])
def test_normalize_subject(raw, expected):
    assert normalize_subject(raw) == expected
