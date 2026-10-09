"""Address-list parsing for From/To/Cc/Bcc (Plan step 5).

A small hand-written splitter instead of email.utils.getaddresses, because
Enron addresses are often not RFC-valid (Lotus "Name/Org/Enron@ENRON",
"terry'.'ed@enron.com", "'/o=enron/...'@enron.com") and must be kept exactly
as written, lowercased. getaddresses also behaves differently across Python
versions for such input.
"""
from __future__ import annotations

import re

COMMENT = re.compile(r"\([^()]*\)")
ANGLE = re.compile(r"<([^<>]*)>")


def _split_top_level(value: str) -> list[str]:
    """Split on commas that are not inside double quotes or angle brackets."""
    parts, buf = [], []
    in_quotes = depth = 0
    for ch in value:
        if ch == '"':
            in_quotes ^= 1
        elif ch == "<" and not in_quotes:
            depth += 1
        elif ch == ">" and not in_quotes and depth:
            depth -= 1
        if ch == "," and not in_quotes and not depth:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _address_from_token(token: str) -> str | None:
    token = token.strip()
    if not token:
        return None
    angles = ANGLE.findall(token)
    if angles:
        addr = angles[-1].strip()
    else:
        addr = COMMENT.sub("", token).strip()
    # group syntax such as "undisclosed-recipients:;" names no actual recipient
    if not addr or addr.endswith(";") or (":" in addr and "@" not in addr):
        return None
    return addr.lower()


def parse_address_list(values: list[str] | str | None) -> list[str]:
    """Parse one or more header values into a list of lowercased addresses (order kept)."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for value in values:
        for token in _split_top_level(value):
            addr = _address_from_token(token)
            if addr:
                out.append(addr)
    return out
