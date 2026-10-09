"""Pipeline defaults and command-line parsing (Plan step 1)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

MAIN_MAILBOXES = ["skilling-j", "sager-e", "arnold-j", "steffes-j", "farmer-d"]


@dataclass
class Config:
    maildir: Path = Path("data/maildir")
    mailboxes: list[str] = field(default_factory=lambda: list(MAIN_MAILBOXES))
    db: Path = Path("data/enron.db")
    output_dir: Path = Path("output")
    error_log: Path = Path("error_log.txt")
    report: Path = Path("duplicates_report.csv")
    reset_db: bool = False
    skip_ingest: bool = False
    # dedup
    dedup_mode: str = "collapse"
    tz_collapse: bool = True
    threshold: float = 90.0
    min_body_chars: int = 20
    # notifications
    send_live: bool = False
    redirect_to: str | None = None
    max_send: int = 10
    send_delay: float = 2.0
    sync_send_log: bool = False
    mcp_config: Path = Path("mcp_config.json")
    # bonuses
    incremental: bool = True
    full_reingest: bool = False
    threads: bool = True
    thread_window_days: int = 14
    batch_size: int = 1000
    ner: bool = False

    @property
    def replies_dir(self) -> Path:
        return self.output_dir / "replies"

    @property
    def send_log(self) -> Path:
        return self.output_dir / "send_log.csv"


def build_parser() -> argparse.ArgumentParser:
    d = Config()
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Enron email extraction, dedup and duplicate-notification pipeline.",
    )
    p.add_argument("--maildir", type=Path, default=d.maildir)
    p.add_argument("--mailboxes", default=",".join(d.mailboxes),
                   help="comma-separated mailbox names (default: the main 5)")
    p.add_argument("--db", type=Path, default=d.db)
    p.add_argument("--output-dir", type=Path, default=d.output_dir)
    p.add_argument("--error-log", type=Path, default=d.error_log)
    p.add_argument("--report", type=Path, default=d.report)
    p.add_argument("--reset-db", action="store_true", help="delete the database before running")
    p.add_argument("--skip-ingest", action="store_true", help="reuse the existing database")

    g = p.add_argument_group("dedup")
    g.add_argument("--dedup-mode", choices=["collapse", "literal"], default=d.dedup_mode,
                   help="collapse folder copies first (default) or apply the spec literally")
    g.add_argument("--no-tz-collapse", dest="tz_collapse", action="store_false",
                   help="do not merge timezone-shifted copies (whole-hour shifts <= 12h, different folders)")
    g.add_argument("--threshold", type=float, default=d.threshold)
    g.add_argument("--min-body-chars", type=int, default=d.min_body_chars)

    g = p.add_argument_group("notifications")
    g.add_argument("--send-live", action="store_true", help="actually send via MCP (default: dry-run)")
    g.add_argument("--redirect-to", default=None, help="test inbox that receives every live send")
    g.add_argument("--max-send", type=int, default=d.max_send)
    g.add_argument("--send-delay", type=float, default=d.send_delay)
    g.add_argument("--mcp-config", type=Path, default=d.mcp_config,
                   help="MCP server config (gitignored; see mcp_config.json.example)")
    g.add_argument("--sync-send-log", action="store_true",
                   help="mark notifications sent from output/send_log.csv (route b)")

    g = p.add_argument_group("bonuses")
    g.add_argument("--no-incremental", dest="incremental", action="store_false")
    g.add_argument("--full-reingest", action="store_true")
    g.add_argument("--no-threads", dest="threads", action="store_false")
    g.add_argument("--thread-window-days", type=int, default=d.thread_window_days)
    g.add_argument("--batch-size", type=int, default=d.batch_size)
    g.add_argument("--ner", action="store_true",
                   help="named-entity extraction with spaCy (bonus; needs spacy + en_core_web_sm)")
    return p


def parse_args(argv: list[str] | None = None) -> Config:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.send_live and not args.redirect_to:
        parser.error("--send-live requires --redirect-to <your test inbox>")
    if args.max_send < 0:
        parser.error("--max-send must be >= 0")
    if args.send_delay < 0:
        parser.error("--send-delay must be >= 0")
    if not 0 < args.threshold <= 100:
        parser.error("--threshold must be in (0, 100]")
    mailboxes = [m.strip() for m in args.mailboxes.split(",") if m.strip()]
    if not mailboxes:
        parser.error("--mailboxes must name at least one mailbox")
    return Config(
        maildir=args.maildir,
        mailboxes=mailboxes,
        db=args.db,
        output_dir=args.output_dir,
        error_log=args.error_log,
        report=args.report,
        reset_db=args.reset_db,
        skip_ingest=args.skip_ingest,
        dedup_mode=args.dedup_mode,
        tz_collapse=args.tz_collapse,
        threshold=args.threshold,
        min_body_chars=args.min_body_chars,
        send_live=args.send_live,
        redirect_to=args.redirect_to,
        max_send=args.max_send,
        send_delay=args.send_delay,
        sync_send_log=args.sync_send_log,
        mcp_config=args.mcp_config,
        incremental=args.incremental,
        full_reingest=args.full_reingest,
        threads=args.threads,
        thread_window_days=args.thread_window_days,
        batch_size=args.batch_size,
        ner=args.ner,
    )
