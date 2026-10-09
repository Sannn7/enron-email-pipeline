"""Find email files under the selected mailboxes (Plan step 2)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path         # absolute/actual path on disk
    source_file: str   # "maildir/<mailbox>/<folder>/<file>", filename kept exactly (e.g. "45.")


def _hidden(name: str) -> bool:
    return name.startswith(".")


def resolve_mailboxes(maildir: Path, mailboxes: list[str]) -> list[str]:
    """["all"] means every visible mailbox directory under maildir."""
    if mailboxes == ["all"]:
        return sorted(p.name for p in maildir.iterdir() if p.is_dir() and not _hidden(p.name))
    return mailboxes


def discover(maildir: Path, mailboxes: list[str]) -> list[DiscoveredFile]:
    """Return every regular, non-hidden file in the given mailboxes, sorted by source_file.

    Missing mailboxes are logged and skipped, never fatal. ["all"] selects every mailbox.
    """
    mailboxes = resolve_mailboxes(maildir, mailboxes) if maildir.is_dir() else mailboxes
    found: list[DiscoveredFile] = []
    for mailbox in mailboxes:
        root = maildir / mailbox
        if not root.is_dir():
            log.warning("mailbox not found, skipping: %s", root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not _hidden(d))
            for name in filenames:
                full = Path(dirpath) / name
                if _hidden(name) or not full.is_file():
                    continue
                rel = full.relative_to(maildir).as_posix()
                found.append(DiscoveredFile(path=full, source_file=f"maildir/{rel}"))
    found.sort(key=lambda f: f.source_file)
    return found
