"""Custom MCP server exposing one tool, send_email, over Gmail SMTP (Plan decision D5).

Run (stdio transport):  python mcp_server/gmail_smtp_server.py
Register in Claude Code: see mcp_config.json.example / README.
Credentials: environment variables only (SMTP_USER, SMTP_PASS, ...; see smtp_send.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import smtp_send  # noqa: E402

mcp = FastMCP("gmail-smtp")


@mcp.tool()
def send_email(to: str, subject: str, body: str, references: str = "", original_to: str = "") -> str:
    """Send a plain-text email through Gmail SMTP.

    Args:
        to: recipient address
        subject: subject line
        body: plain-text body
        references: Message-ID this email refers to (sets References and In-Reply-To)
        original_to: the intended recipient when the send is redirected to a test inbox
    """
    message_id = smtp_send.send_email(to, subject, body, references, original_to)
    return f"sent {message_id} to {to}"


if __name__ == "__main__":
    mcp.run()
