"""duplicates_report.csv (Plan step 13), generated from the database flags."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

SPEC_COLUMNS = ["duplicate_message_id", "original_message_id", "subject", "from_address",
                "duplicate_date", "original_date", "similarity_score"]
EXTRA_COLUMNS = ["duplicate_source_file", "original_source_file"]
COLUMNS = SPEC_COLUMNS + EXTRA_COLUMNS

REPORT_QUERY = """
    SELECT d.message_id, o.message_id, d.subject, d.from_address,
           d.date, o.date, d.similarity_score, d.source_file, o.source_file
    FROM emails d
    JOIN emails o ON o.message_id = d.duplicate_of
    WHERE d.is_duplicate = 1
    ORDER BY d.from_address, o.date, o.source_file, d.date, d.source_file
"""


def report_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(REPORT_QUERY).fetchall()


def write_report(conn: sqlite3.Connection, path: Path) -> int:
    """Write one row per flagged duplicate; returns the row count."""
    rows = report_rows(conn)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            row = list(row)
            row[6] = f"{row[6]:.2f}"
            writer.writerow(row)
    return len(rows)
