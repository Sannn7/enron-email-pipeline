import pytest

from config import MAIN_MAILBOXES, parse_args


def test_defaults_are_safe():
    c = parse_args([])
    assert c.send_live is False          # dry-run by default
    assert c.max_send == 10
    assert c.send_delay == 2.0
    assert c.threshold == 90.0
    assert c.min_body_chars == 20
    assert c.dedup_mode == "collapse"
    assert c.tz_collapse is True
    assert c.mailboxes == MAIN_MAILBOXES
    assert c.incremental and c.threads
    assert c.thread_window_days == 14
    assert str(c.replies_dir) == "output/replies"
    assert str(c.send_log) == "output/send_log.csv"


def test_live_without_redirect_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--send-live"])
    assert "--redirect-to" in capsys.readouterr().err


def test_live_with_redirect_ok():
    c = parse_args(["--send-live", "--redirect-to", "me@example.com", "--max-send", "3"])
    assert c.send_live and c.redirect_to == "me@example.com" and c.max_send == 3


@pytest.mark.parametrize("argv", [["--max-send", "-1"], ["--send-delay", "-0.5"],
                                  ["--threshold", "0"], ["--threshold", "101"], ["--mailboxes", " , "]])
def test_invalid_values_rejected(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_mailboxes_and_flags():
    c = parse_args(["--mailboxes", "a-b, c-d", "--dedup-mode", "literal", "--no-threads",
                    "--no-incremental", "--thread-window-days", "7", "--no-tz-collapse"])
    assert c.mailboxes == ["a-b", "c-d"]
    assert c.dedup_mode == "literal"
    assert not c.threads and not c.incremental
    assert c.thread_window_days == 7
    assert c.tz_collapse is False
