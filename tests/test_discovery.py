from pipeline.discovery import discover


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def test_discovers_nested_files_keeps_trailing_dot(tmp_path):
    md = tmp_path / "maildir"
    _touch(md / "lay-k" / "inbox" / "45.")
    _touch(md / "lay-k" / "sent" / "2001" / "1.")
    _touch(md / "lay-k" / "inbox" / ".DS_Store")
    _touch(md / "lay-k" / ".hidden" / "1.")
    _touch(md / "other-m" / "inbox" / "1.")  # not selected
    files = discover(md, ["lay-k"])
    assert [f.source_file for f in files] == ["maildir/lay-k/inbox/45.", "maildir/lay-k/sent/2001/1."]
    assert files[0].path == md / "lay-k" / "inbox" / "45."


def test_missing_mailbox_is_skipped_not_fatal(tmp_path, caplog):
    md = tmp_path / "maildir"
    _touch(md / "a-b" / "inbox" / "1.")
    files = discover(md, ["nope-x", "a-b"])
    assert [f.source_file for f in files] == ["maildir/a-b/inbox/1."]
    assert "nope-x" in caplog.text


def test_sorted_across_mailboxes(tmp_path):
    md = tmp_path / "maildir"
    _touch(md / "z-z" / "inbox" / "1.")
    _touch(md / "a-a" / "inbox" / "2.")
    _touch(md / "a-a" / "inbox" / "10.")
    assert [f.source_file for f in discover(md, ["z-z", "a-a"])] == [
        "maildir/a-a/inbox/10.", "maildir/a-a/inbox/2.", "maildir/z-z/inbox/1."]
