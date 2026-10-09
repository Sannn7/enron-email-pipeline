"""Discover -> extract -> store -> stats (stages S1-S5).

Run on its own:  python -m pipeline.ingest [main.py flags]
"""
from __future__ import annotations

import logging
import sys

from config import Config, parse_args
from pipeline.db import EmailStore, connect, init_schema, write_error_log
from pipeline.discovery import discover
from pipeline.extract import extract_file
from pipeline.models import EmailRecord
from pipeline.stats import ExtractionStats

log = logging.getLogger(__name__)


def run_ingest(config: Config) -> ExtractionStats:
    if config.reset_db and config.db.exists():
        config.db.unlink()
    conn = connect(config.db)
    init_schema(conn)
    store = EmailStore(conn)
    stats = ExtractionStats()

    files = discover(config.maildir, config.mailboxes)
    stats.found = len(files)
    log.info("discovered %d files in %d mailboxes", len(files), len(config.mailboxes))

    batch, failures = [], []

    def flush():
        result = store.insert_records(batch)
        stats.inserted += result.inserted
        stats.skipped_existing += result.skipped_existing
        store.insert_failures(failures)
        batch.clear()
        failures.clear()

    for f in files:
        result = extract_file(f.path, f.source_file)
        if isinstance(result, EmailRecord):
            stats.add_record(result)
            batch.append(result)
        else:
            stats.add_failure(result)
            failures.append(result)
        if len(batch) + len(failures) >= config.batch_size:
            flush()
    flush()

    write_error_log(conn, config.error_log)
    stats.write_json(config.output_dir / "extraction_stats.json")
    conn.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = run_ingest(parse_args(argv))
    print(stats.format())
    return 0


if __name__ == "__main__":
    sys.exit(main())
