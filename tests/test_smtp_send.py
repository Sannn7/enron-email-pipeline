import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
import smtp_send  # noqa: E402

ENV = {"SMTP_USER": "me@gmail.com", "SMTP_PASS": "abcd efgh ijkl mnop"}


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.events, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.events.append("quit")

    def starttls(self):
        self.events.append("starttls")

    def login(self, user, password):
        self.events.append(("login", user, password))

    def send_message(self, msg):
        self.sent.append(msg)


def test_sends_over_starttls_with_env_credentials():
    FakeSMTP.instances.clear()
    mid = smtp_send.send_email("me@gmail.com", "[Duplicate Notice] Re: X", "body", references="<d@x>",
                               original_to="john@enron.com", env=ENV, smtp_factory=FakeSMTP)
    s = FakeSMTP.instances[0]
    assert (s.host, s.port) == ("smtp.gmail.com", 587)
    assert s.events == ["starttls", ("login", "me@gmail.com", "abcd efgh ijkl mnop"), "quit"]
    msg = s.sent[0]
    assert msg["To"] == "me@gmail.com" and msg["From"] == "me@gmail.com"
    assert msg["References"] == "<d@x>" and msg["X-Original-To"] == "john@enron.com"
    assert msg["Message-ID"] == mid and msg.get_content().strip() == "body"


def test_missing_credentials_raise():
    with pytest.raises(smtp_send.SmtpConfigError):
        smtp_send.send_email("a@b.com", "s", "b", env={"SMTP_USER": "me@gmail.com"}, smtp_factory=FakeSMTP)


def test_settings_overrides():
    cfg = smtp_send.smtp_settings({**ENV, "SMTP_HOST": "localhost", "SMTP_PORT": "2525", "SMTP_FROM": "x@y.z"})
    assert (cfg["host"], cfg["port"], cfg["sender"]) == ("localhost", 2525, "x@y.z")


def test_no_credentials_in_repo_example():
    text = (Path(__file__).resolve().parent.parent / "mcp_config.json.example").read_text()
    assert "<your_gmail_address>" in text and "<your_16_char_gmail_app_password>" in text
