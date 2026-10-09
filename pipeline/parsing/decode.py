"""Bytes -> text (Plan step 3).

The CMU Enron copy is pure ASCII (0 non-ASCII bytes in 517k files), so this
stays minimal: UTF-8 if valid, otherwise cp1252, otherwise latin-1, which can
decode any byte and therefore never fails.
"""
from __future__ import annotations


def decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")
