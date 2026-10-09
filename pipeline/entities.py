"""Named-entity extraction bonus (stage S10, only with --ner).

spaCy en_core_web_sm with every component except tok2vec + ner disabled,
run with nlp.pipe batching over body, forwarded_content and quoted_content of
the emails left after copy collapse (is_copy = 0). Labels kept: PERSON, ORG,
DATE, GPE. Results go to the entities table with a source column, so
statistics can use body only while search can use all three.

Idempotent: before inserting, every existing entity row of the emails being
processed is deleted, in the same transaction.

Input text is the stored text with quoted-printable leftovers (=20, =3D, =09,
soft line breaks) removed and capped at MAX_CHARS per field; line breaks are
kept because many Enron bodies are one-name-per-line lists. Offsets refer to
that cleaned text.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

LABELS = ("PERSON", "ORG", "DATE", "GPE")
FIELDS = (("body", "body"), ("forwarded_content", "forwarded"), ("quoted_content", "quoted"))
MODEL = "en_core_web_sm"
MAX_CHARS = 10_000
BATCH_SIZE = 64

QP_SOFT_BREAK = re.compile(r"=\r?\n")
QP_CODES = {"=20": " ", "=3D": "=", "=09": "\t"}
WS = re.compile(r"\s+")
HAS_ALNUM = re.compile(r"[A-Za-z0-9]")


def clean_for_ner(text: str | None, max_chars: int = MAX_CHARS) -> str:
    """Stored text -> NER input: QP artifacts removed, CRLF -> LF, line breaks kept, capped."""
    if not text:
        return ""
    text = QP_SOFT_BREAK.sub("", text.replace("\r\n", "\n"))
    for code, ch in QP_CODES.items():
        text = text.replace(code, ch)
    return text[:max_chars]


def load_model(name: str = MODEL):
    """Load spaCy keeping only what NER needs (tok2vec + ner)."""
    import spacy

    nlp = spacy.load(name)
    keep = {"tok2vec", "ner"}
    nlp.select_pipes(enable=[p for p in nlp.pipe_names if p in keep])
    return nlp


def split_at_line_breaks(text: str, start: int) -> list[tuple[str, int, int]]:
    """Split an entity span at line breaks when EVERY piece has 2+ words.

    spaCy merges consecutive lines of a list into one entity
    ("CMS Marketing, ... Company\\nCalpine Energy Services"). Splitting fixes that, while
    the 2-word guard keeps hard-wrapped names together ("Kenneth\\nLay" stays one PERSON).
    Returns (piece_text, start_char, end_char) with offsets in the original text.
    """
    if "\n" not in text:
        return [(text, start, start + len(text))]
    pieces, pos = [], 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            offset = pos + line.index(stripped)
            pieces.append((stripped, start + offset, start + offset + len(stripped)))
        pos += len(line) + 1
    if len(pieces) > 1 and all(len(p[0].split()) >= 2 for p in pieces):
        return pieces
    return [(text, start, start + len(text))]


def extract(nlp, texts: list[str], batch_size: int = BATCH_SIZE) -> list[list[tuple[str, str, int, int]]]:
    """For each text: [(entity_text, label, start, end)] restricted to LABELS."""
    out = []
    for doc in nlp.pipe(texts, batch_size=batch_size):
        ents = []
        for e in doc.ents:
            if e.label_ not in LABELS:
                continue
            for piece, start, end in split_at_line_breaks(e.text, e.start_char):
                text = WS.sub(" ", piece).strip()
                if len(text) >= 2 and HAS_ALNUM.search(text):
                    ents.append((text, e.label_, start, end))
        out.append(ents)
    return out


@dataclass
class NerStats:
    emails: int = 0
    texts: int = 0
    entities: int = 0
    seconds: float = 0.0
    by_label: Counter = field(default_factory=Counter)
    by_source: Counter = field(default_factory=Counter)
    by_label_source: Counter = field(default_factory=Counter)

    @property
    def emails_per_second(self) -> float:
        return round(self.emails / self.seconds, 1) if self.seconds else 0.0

    def to_dict(self) -> dict:
        return {"emails": self.emails, "texts": self.texts, "entities": self.entities,
                "seconds": round(self.seconds, 1), "emails_per_second": self.emails_per_second,
                "by_label": dict(self.by_label), "by_source": dict(self.by_source),
                "by_label_source": {f"{l}/{s}": n for (l, s), n in sorted(self.by_label_source.items())}}

    def format(self) -> str:
        return (f"NER: {self.emails:,} emails, {self.texts:,} texts -> {self.entities:,} entities in "
                f"{self.seconds:.1f}s ({self.emails_per_second} emails/s) | "
                + ", ".join(f"{l} {self.by_label[l]:,}" for l in LABELS))


def run_ner(conn: sqlite3.Connection, nlp=None, limit: int | None = None,
            chunk_emails: int = 500, batch_size: int = BATCH_SIZE) -> NerStats:
    """Extract entities for non-copy emails (all of them, or the first `limit` by id)."""
    start = time.perf_counter()
    nlp = nlp or load_model()
    stats = NerStats()
    sql = "SELECT id, body, forwarded_content, quoted_content FROM emails WHERE is_copy = 0 ORDER BY id"
    rows = conn.execute(sql + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    for i in range(0, len(rows), chunk_emails):
        chunk = rows[i:i + chunk_emails]
        keys, texts = [], []
        for email_id, *values in chunk:
            for (_, source), value in zip(FIELDS, values):
                text = clean_for_ner(value)
                if text.strip():
                    keys.append((email_id, source))
                    texts.append(text)
        results = extract(nlp, texts, batch_size)
        inserts = [(email_id, t, label, source, s, e)
                   for (email_id, source), ents in zip(keys, results) for t, label, s, e in ents]
        with conn:
            conn.executemany("DELETE FROM entities WHERE email_id = ?", [(r[0],) for r in chunk])
            conn.executemany("INSERT OR IGNORE INTO entities (email_id, text, label, source, start_char, end_char) "
                             "VALUES (?, ?, ?, ?, ?, ?)", inserts)
        stats.emails += len(chunk)
        stats.texts += len(texts)
        for _, _, label, source, _, _ in inserts:
            stats.by_label[label] += 1
            stats.by_source[source] += 1
            stats.by_label_source[(label, source)] += 1
        stats.entities += len(inserts)
    stats.seconds = time.perf_counter() - start
    return stats


def main(argv: list[str] | None = None) -> int:
    """Timing helper: python -m pipeline.entities [--limit 500] [--db data/enron.db]"""
    import argparse

    from pipeline.db import connect, init_schema

    p = argparse.ArgumentParser(description="Run NER on the database (timing helper).")
    p.add_argument("--db", default="data/enron.db")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    conn = connect(args.db)
    init_schema(conn)
    t0 = time.perf_counter()
    nlp = load_model()
    load_s = time.perf_counter() - t0
    stats = run_ner(conn, nlp=nlp, limit=args.limit)
    total = conn.execute("SELECT COUNT(*) FROM emails WHERE is_copy = 0").fetchone()[0]
    print(f"model load {load_s:.1f}s")
    print(stats.format())
    if args.limit and stats.emails:
        projected = stats.seconds / stats.emails * total
        print(f"projected for all {total:,} non-copy emails: {projected:.0f}s (~{projected / 60:.1f} min) + model load")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
