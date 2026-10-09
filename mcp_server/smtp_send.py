"""SMTP sending used by the MCP server. Plain Python, no MCP dependency, so it is testable alone.

Credentials come only from environment variables:
    SMTP_USER   Gmail address (required)
    SMTP_PASS   Gmail App Password (required; https://myaccount.google.com/apppasswords)
    SMTP_HOST   default smtp.gmail.com
    SMTP_PORT   default 587 (STARTTLS)
    SMTP_FROM   default SMTP_USER
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


class SmtpConfigError(RuntimeError):
    pass


def smtp_settings(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    user, password = env.get("SMTP_USER", "").strip(), env.get("SMTP_PASS", "").strip()
    if not user or not password:
        raise SmtpConfigError("SMTP_USER and SMTP_PASS must be set in the environment")
    return {
        "host": env.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(env.get("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "sender": env.get("SMTP_FROM", user),
    }


def build_message(sender: str, to: str, subject: str, body: str,
                  references: str = "", original_to: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or "localhost")
    if references:
        msg["References"] = references
        msg["In-Reply-To"] = references
    if original_to:
        msg["X-Original-To"] = original_to   # live sends are redirected to a test inbox
    msg.set_content(body)
    return msg


def send_email(to: str, subject: str, body: str, references: str = "", original_to: str = "",
               env: dict | None = None, smtp_factory=smtplib.SMTP) -> str:
    """Send one email over STARTTLS. Returns the new Message-ID; raises on any failure."""
    cfg = smtp_settings(env)
    msg = build_message(cfg["sender"], to, subject, body, references, original_to)
    with smtp_factory(cfg["host"], cfg["port"], timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)
    return msg["Message-ID"]
