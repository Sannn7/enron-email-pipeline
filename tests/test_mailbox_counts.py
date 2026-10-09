import csv

import pytest

from scripts.mailbox_counts import (
    ROOT_FOLDER,
    count_mailbox,
    count_mailboxes,
    format_table,
    main,
    write_csv,
)


def _touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def maildir(tmp_path):
    root = tmp_path / "maildir"
    # big-a: 3 inbox + 2 nested sent + 1 root file = 6
    for i in range(1, 4):
        _touch(root / "big-a" / "inbox" / str(i))
    _touch(root / "big-a" / "sent" / "2001" / "1")
    _touch(root / "big-a" / "sent" / "2001" / "2")
    _touch(root / "big-a" / "loose")
    # small-b: 2 files + hidden noise that must be ignored
    _touch(root / "small-b" / "inbox" / "1")
    _touch(root / "small-b" / "inbox" / "2")
    _touch(root / "small-b" / "inbox" / ".DS_Store")
    _touch(root / "small-b" / ".hidden_dir" / "1")
    # empty mailbox
    (root / "empty-c").mkdir(parents=True)
    # noise at maildir root: a file and a hidden dir, not mailboxes
    _touch(root / "README")
    _touch(root / ".cache" / "1")
    return root


def test_counts_recursively_and_by_top_folder(maildir):
    c = count_mailbox(maildir / "big-a")
    assert c.total_files == 6
    assert c.folder_counts == {"inbox": 3, "sent": 2, ROOT_FOLDER: 1}
    assert c.folder_count == 3


def test_hidden_files_and_dirs_skipped(maildir):
    c = count_mailbox(maildir / "small-b")
    assert c.total_files == 2
    assert c.folder_counts == {"inbox": 2}


def test_empty_mailbox_is_zero(maildir):
    c = count_mailbox(maildir / "empty-c")
    assert c.total_files == 0
    assert c.folder_counts == {}


def test_only_visible_dirs_are_mailboxes_sorted_desc(maildir):
    counts = count_mailboxes(maildir)
    assert [c.mailbox for c in counts] == ["big-a", "small-b", "empty-c"]
    assert [c.total_files for c in counts] == [6, 2, 0]


def test_ties_sorted_by_name(tmp_path):
    root = tmp_path / "maildir"
    _touch(root / "zeta" / "inbox" / "1")
    _touch(root / "alpha" / "inbox" / "1")
    assert [c.mailbox for c in count_mailboxes(root)] == ["alpha", "zeta"]


def test_top_folders_ordering(maildir):
    c = count_mailbox(maildir / "big-a")
    assert c.top_folders(2) == [("inbox", 3), ("sent", 2)]


def test_missing_maildir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        count_mailboxes(tmp_path / "nope")


def test_main_missing_maildir_returns_1(tmp_path, capsys):
    assert main(["--maildir", str(tmp_path / "nope")]) == 1
    assert "maildir not found" in capsys.readouterr().err


def test_format_table_has_rows_and_total(maildir):
    table = format_table(count_mailboxes(maildir))
    assert "big-a" in table and "small-b" in table and "empty-c" in table
    assert table.splitlines()[-1] == "Total: 3 mailboxes, 8 files"


def test_write_csv(maildir, tmp_path):
    out = tmp_path / "out" / "counts.csv"
    write_csv(count_mailboxes(maildir), out)
    rows = list(csv.DictReader(out.open()))
    assert [r["mailbox"] for r in rows] == ["big-a", "small-b", "empty-c"]
    assert rows[0]["total_files"] == "6"
    assert rows[0]["top_folders"] == "inbox=3; sent=2; (root)=1"


def test_main_success_writes_csv(maildir, tmp_path, capsys):
    out = tmp_path / "counts.csv"
    assert main(["--maildir", str(maildir), "--csv", str(out)]) == 0
    assert out.exists()
    assert "Total: 3 mailboxes, 8 files" in capsys.readouterr().out
