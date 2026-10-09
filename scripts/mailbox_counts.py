"""Count email files per mailbox in the Enron maildir (Plan step 0.2).

Usage:
    python scripts/mailbox_counts.py [--maildir data/maildir] [--csv output/mailbox_counts.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT_FOLDER = "(root)"  # label for files sitting directly in a mailbox dir


@dataclass
class MailboxCount:
    mailbox: str
    total_files: int = 0
    folder_counts: dict[str, int] = field(default_factory=dict)

    @property
    def folder_count(self) -> int:
        return len(self.folder_counts)

    def top_folders(self, n: int = 3) -> list[tuple[str, int]]:
        return sorted(self.folder_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def count_mailbox(mailbox_dir: Path) -> MailboxCount:
    """Count regular, non-hidden files under one mailbox, grouped by top-level folder."""
    result = MailboxCount(mailbox=mailbox_dir.name)
    for dirpath, dirnames, filenames in os.walk(mailbox_dir):
        dirnames[:] = [d for d in dirnames if not _is_hidden(d)]
        rel = Path(dirpath).relative_to(mailbox_dir)
        folder = rel.parts[0] if rel.parts else ROOT_FOLDER
        for name in filenames:
            if _is_hidden(name) or not os.path.isfile(os.path.join(dirpath, name)):
                continue
            result.total_files += 1
            result.folder_counts[folder] = result.folder_counts.get(folder, 0) + 1
    return result


def count_mailboxes(maildir: Path) -> list[MailboxCount]:
    """Count every mailbox under maildir, sorted by file count (desc), then name."""
    if not maildir.is_dir():
        raise FileNotFoundError(f"maildir not found: {maildir}")
    counts = [
        count_mailbox(entry)
        for entry in maildir.iterdir()
        if entry.is_dir() and not _is_hidden(entry.name)
    ]
    counts.sort(key=lambda c: (-c.total_files, c.mailbox))
    return counts


def format_table(counts: list[MailboxCount]) -> str:
    lines = [f"{'#':>4}  {'mailbox':<20} {'files':>7} {'folders':>8}  top folders"]
    for i, c in enumerate(counts, 1):
        top = ", ".join(f"{name} ({n})" for name, n in c.top_folders())
        lines.append(f"{i:>4}  {c.mailbox:<20} {c.total_files:>7,} {c.folder_count:>8}  {top}")
    total = sum(c.total_files for c in counts)
    lines.append(f"Total: {len(counts)} mailboxes, {total:,} files")
    return "\n".join(lines)


def write_csv(counts: list[MailboxCount], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mailbox", "total_files", "folder_count", "top_folders"])
        for c in counts:
            top = "; ".join(f"{name}={n}" for name, n in c.top_folders())
            writer.writerow([c.mailbox, c.total_files, c.folder_count, top])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count email files per Enron mailbox.")
    parser.add_argument("--maildir", type=Path, default=Path("data/maildir"))
    parser.add_argument("--csv", type=Path, default=None, help="optional CSV output path")
    args = parser.parse_args(argv)

    try:
        counts = count_mailboxes(args.maildir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_table(counts))
    if args.csv:
        write_csv(counts, args.csv)
        print(f"CSV written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
