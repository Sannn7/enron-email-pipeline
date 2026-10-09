"""Enron email pipeline: one command runs everything (dry-run by default).

    python main.py                                   # ingest -> copies -> dedup -> report -> .eml drafts
    python main.py --send-live --redirect-to me@x    # same, then send (max 10, y/N confirmation)
    python main.py --sync-send-log                   # mark sends made through Claude Code (route b)
    python main.py --ner                             # + named-entity extraction (bonus)
    python main.py --help
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from config import parse_args
from pipeline.dedup import run_dedup
from pipeline.ingest import run_ingest
from pipeline.notify.run import run_notify


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    cfg = parse_args(argv)
    timings: dict[str, float] = {}
    summary: dict = {"mode": "live" if cfg.send_live else "dry-run", "mailboxes": cfg.mailboxes}

    def stage(name):
        timings[name] = time.perf_counter()

    def done(name):
        timings[name] = round(time.perf_counter() - timings[name], 2)

    print(f"Enron pipeline ({summary['mode']}) on {cfg.maildir} : {', '.join(cfg.mailboxes)}")

    if cfg.skip_ingest:
        print("[S1-S5] ingest skipped (--skip-ingest), using", cfg.db)
    else:
        stage("ingest")
        stats = run_ingest(cfg)
        done("ingest")
        summary["extraction"] = stats.to_dict()
        print(f"[S1-S5] {stats.found:,} files | parsed {stats.parsed:,} | failed {stats.failed:,} "
              f"-> {cfg.error_log} | inserted {stats.inserted:,} | already in DB {stats.skipped_existing:,}")

    stage("dedup")
    copy_stats, tz_stats, dedup_stats, report_rows = run_dedup(cfg)
    done("dedup")
    summary["copy_collapse"] = vars(copy_stats)
    summary["tz_shift_collapse"] = vars(tz_stats) if tz_stats else None
    summary["dedup"] = dedup_stats.to_dict()
    print(f"[S6]    {copy_stats.format()}")
    print(f"        {tz_stats.format() if tz_stats else 'Timezone-shifted copy stage: disabled'}")
    print(f"[S7-S8] {dedup_stats.groups:,} duplicate groups | {dedup_stats.flagged:,} flagged | "
          f"avg group size {dedup_stats.avg_group_size} -> {cfg.report} ({report_rows:,} rows)")

    if cfg.ner:
        stage("ner")
        try:  # bonus stage: a failure here never stops the core pipeline
            from pipeline.db import connect
            from pipeline.entities import run_ner

            conn = connect(cfg.db)
            ner_stats = run_ner(conn)
            conn.close()
            summary["ner"] = ner_stats.to_dict()
            print(f"[S10]   {ner_stats.format()}")
        except Exception as exc:
            summary["ner"] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[S10]   NER skipped ({type(exc).__name__}: {exc}); core pipeline continues")
        done("ner")

    stage("notify")
    notify = run_notify(cfg)
    done("notify")
    summary["notify"] = notify
    if "synced_from_send_log" in notify:
        print(f"[S11]   synced {notify['synced_from_send_log']} send(s) from {cfg.send_log}")
    print(f"[S11]   {notify['eml_written']:,} .eml drafts -> {cfg.replies_dir}/ | "
          f"{notify['pending_live_targets']:,} live targets pending (latest per group, not yet notified)")
    if "live" in notify:
        print(f"        live: {notify['live']}")
    else:
        print("        dry-run: nothing sent (use --send-live --redirect-to <inbox>)")

    summary["timings_s"] = timings
    out = Path(cfg.output_dir) / "run_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"[S12]   summary -> {out}  (stage seconds: {timings})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
