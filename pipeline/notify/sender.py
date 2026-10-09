"""Choose who to notify, send with safeguards, log, and track (Plan step 15).

Safeguards (spec 4.3): live sends need --redirect-to (approved by the AISH team),
a printed summary and an explicit y/N, at most --max-send per run, --send-delay
seconds between sends, every attempt logged to send_log.csv, and
notification_sent / notification_date so a duplicate is never notified twice.
"""
from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pipeline.notify.template import Notification, build_notification

SEND_LOG_COLUMNS = ["timestamp", "recipient", "subject", "message_id_referenced", "status", "error_message"]
SEND_LOG_EXTRA = ["original_recipient"]   # the real sender; live sends go to the redirect inbox

PAIR_QUERY = """
    SELECT d.message_id, d.date, d.subject, d.from_address, d.similarity_score, d.source_file,
           o.message_id, o.date, o.subject, o.from_address
    FROM emails d JOIN emails o ON o.message_id = d.duplicate_of
    WHERE d.is_duplicate = 1 {extra}
    ORDER BY d.from_address, o.date, d.date, d.source_file
"""
# latest flagged member of its group (by date, then source_file), not yet notified
LATEST_FILTER = """
    AND d.notification_sent = 0
    AND NOT EXISTS (SELECT 1 FROM emails x
                    WHERE x.is_duplicate = 1 AND x.duplicate_of = d.duplicate_of
                      AND (x.date > d.date OR (x.date = d.date AND x.source_file > d.source_file)))
"""


def _pairs(conn: sqlite3.Connection, extra: str = "") -> list[Notification]:
    out = []
    for r in conn.execute(PAIR_QUERY.format(extra=extra)):
        dup = {"message_id": r[0], "date": r[1], "subject": r[2], "from_address": r[3], "similarity_score": r[4]}
        orig = {"message_id": r[6], "date": r[7], "subject": r[8], "from_address": r[9]}
        out.append(build_notification(dup, orig))
    return out


def all_notifications(conn: sqlite3.Connection) -> list[Notification]:
    """One notification per flagged duplicate (dry-run .eml drafts)."""
    return _pairs(conn)


def pending_targets(conn: sqlite3.Connection) -> list[Notification]:
    """Latest duplicate of each group that has not been notified yet (live sends)."""
    return _pairs(conn, LATEST_FILTER)


@dataclass
class SendResult:
    pending: int = 0
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    aborted: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_send_log(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SEND_LOG_COLUMNS + SEND_LOG_EXTRA)
        if new:
            w.writeheader()
        w.writerow(row)


def mark_notified(conn: sqlite3.Connection, message_id: str, when: str) -> None:
    with conn:
        conn.execute("UPDATE emails SET notification_sent = 1, notification_date = ? "
                     "WHERE message_id = ? AND notification_sent = 0", (when, message_id))


def send_notifications(conn, targets: list[Notification], client, redirect_to: str, max_send: int,
                       delay: float, log_path: Path, input_fn=input, sleep_fn=time.sleep,
                       now_fn=_utc_now, out=print) -> SendResult:
    if not redirect_to:
        raise ValueError("live sending requires a redirect address (--redirect-to)")
    result = SendResult(pending=len(targets))
    batch = targets[:max_send]
    out(f"{len(targets)} notification(s) pending (latest duplicate per group, not yet notified).")
    out(f"This run will send {len(batch)} (--max-send {max_send}), {delay:g}s apart, all to {redirect_to}:")
    for i, n in enumerate(batch, 1):
        out(f"  {i:>2}. -> {redirect_to} (redirected from {n.to}) | {n.subject[:80]}")
    if not batch:
        return result
    if input_fn("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
        out("Aborted: nothing sent.")
        result.aborted = True
        return result

    for i, n in enumerate(batch):
        if i:
            sleep_fn(delay)
        result.attempted += 1
        ts = now_fn()
        try:
            client.send_email(to=redirect_to, subject=n.subject, body=n.body,
                              references=n.references, original_to=n.to)
            status, error = "sent", ""
        except Exception as exc:  # log and continue with the next one
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        append_send_log(log_path, {"timestamp": ts, "recipient": redirect_to, "subject": n.subject,
                                   "message_id_referenced": n.duplicate_message_id, "status": status,
                                   "error_message": error, "original_recipient": n.to})
        if status == "sent":
            mark_notified(conn, n.duplicate_message_id, ts)
            result.sent += 1
        else:
            result.failed += 1
        out(f"  [{status}] {n.duplicate_message_id} {error}".rstrip())
    return result


def sync_send_log(conn: sqlite3.Connection, log_path: Path) -> int:
    """Route (b): mark duplicates notified from send_log.csv rows written after Claude Code sent them."""
    if not log_path.exists():
        return 0
    marked = 0
    with log_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") == "sent":
                cur = conn.execute("UPDATE emails SET notification_sent = 1, notification_date = ? "
                                   "WHERE message_id = ? AND notification_sent = 0",
                                   (row["timestamp"], row["message_id_referenced"]))
                marked += cur.rowcount
    conn.commit()
    return marked
