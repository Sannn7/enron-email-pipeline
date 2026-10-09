"""Stage S11: dry-run drafts, route-(b) payloads, optional live send.

Run on its own:  python -m pipeline.notify.run [--send-live --redirect-to you@gmail.com]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from pipeline.db import connect, init_schema
from pipeline.notify.eml_writer import write_all
from pipeline.notify.sender import all_notifications, pending_targets, send_notifications, sync_send_log


def run_notify(config, input_fn=input, client=None, now: datetime | None = None, out=print) -> dict:
    now = now or datetime.now(timezone.utc)
    conn = connect(config.db)
    init_schema(conn)
    summary: dict = {}

    if config.sync_send_log:
        summary["synced_from_send_log"] = sync_send_log(conn, config.send_log)

    drafts = all_notifications(conn)
    summary["eml_written"] = write_all(drafts, config.replies_dir, now)

    targets = pending_targets(conn)
    summary["pending_live_targets"] = len(targets)
    payloads = [{"to": config.redirect_to or "<--redirect-to address>", "original_to": n.to,
                 "subject": n.subject, "body": n.body, "references": n.references} for n in targets]
    pending_path = config.output_dir / "pending_notifications.json"
    pending_path.write_text(json.dumps(payloads, indent=2) + "\n")

    if config.send_live:
        if client is None:
            from pipeline.notify.mcp_client import McpEmailClient
            client = McpEmailClient(config.mcp_config)
        result = send_notifications(conn, targets, client, config.redirect_to, config.max_send,
                                    config.send_delay, config.send_log, input_fn=input_fn, out=out)
        summary["live"] = vars(result)
    conn.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    from config import parse_args

    cfg = parse_args(argv)
    s = run_notify(cfg)
    mode = "LIVE" if cfg.send_live else "DRY-RUN"
    print(f"{mode}: {s['eml_written']:,} drafts -> {cfg.replies_dir}/ ; "
          f"{s['pending_live_targets']:,} pending live targets (latest per group) -> "
          f"{cfg.output_dir / 'pending_notifications.json'}")
    if "live" in s:
        print(f"live result: {s['live']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
