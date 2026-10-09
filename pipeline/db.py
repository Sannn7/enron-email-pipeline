"""SQLite storage (Plan step 9)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pipeline.models import EmailRecord, ParseFailure

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection, schema_path: Path = SCHEMA_PATH) -> None:
    conn.executescript(schema_path.read_text())


@dataclass
class InsertResult:
    inserted: int = 0
    skipped_existing: int = 0  # message_id (or source_file) already in the DB


class EmailStore:
    """Inserts records with normalized recipients; keeps an address-id cache."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._address_ids: dict[str, int] = {}

    def _address_id(self, email: str) -> int:
        cached = self._address_ids.get(email)
        if cached is not None:
            return cached
        self.conn.execute("INSERT OR IGNORE INTO addresses (email) VALUES (?)", (email,))
        row = self.conn.execute("SELECT id FROM addresses WHERE email = ?", (email,)).fetchone()
        self._address_ids[email] = row[0]
        return row[0]

    def insert_records(self, records: list[EmailRecord]) -> InsertResult:
        """Insert a batch in one transaction. Existing message_ids are skipped, not updated."""
        result = InsertResult()
        with self.conn:
            for r in records:
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO emails (
                           message_id, date, from_address, subject, body, source_file,
                           x_from, x_to, x_cc, x_bcc, x_folder, x_origin, content_type,
                           has_attachment, forwarded_content, quoted_content,
                           in_reply_to, references_hdr, normalized_subject, body_hash, copy_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (r.message_id, r.date, r.from_address, r.subject, r.body, r.source_file,
                     r.x_from, r.x_to, r.x_cc, r.x_bcc, r.x_folder, r.x_origin, r.content_type,
                     int(r.has_attachment), r.forwarded_content, r.quoted_content,
                     r.in_reply_to, r.references, r.normalized_subject, r.body_hash, r.copy_key),
                )
                if cur.rowcount == 0:
                    result.skipped_existing += 1
                    continue
                email_id = cur.lastrowid
                recipients = [
                    (email_id, self._address_id(addr), kind, pos)
                    for kind, addrs in (("to", r.to_addresses), ("cc", r.cc_addresses), ("bcc", r.bcc_addresses))
                    for pos, addr in enumerate(addrs or [])
                ]
                self.conn.executemany(
                    "INSERT INTO email_recipients (email_id, address_id, recipient_type, position) "
                    "VALUES (?, ?, ?, ?)", recipients)
                self.conn.executemany(
                    "INSERT OR IGNORE INTO attachments (email_id, filename) VALUES (?, ?)",
                    [(email_id, name) for name in r.attachments])
                result.inserted += 1
        return result

    def insert_failures(self, failures: list[ParseFailure]) -> None:
        """Record parse failures; a re-run replaces the previous entry for the same file."""
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO parse_failures (source_file, reason, detail) VALUES (?, ?, ?)",
                [(f.source_file, f.reason, f.detail) for f in failures])


def write_error_log(conn: sqlite3.Connection, path: Path) -> int:
    """Rewrite error_log.txt from the parse_failures table. Returns the number of lines."""
    rows = conn.execute(
        "SELECT logged_at, source_file, reason, detail FROM parse_failures ORDER BY source_file").fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("# timestamp | source_file | reason | detail\n")
        for row in rows:
            detail = (row["detail"] or "").replace("\n", " ")
            f.write(f"{row['logged_at']} | {row['source_file']} | {row['reason']} | {detail}\n")
    return len(rows)
