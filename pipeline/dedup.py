"""Fuzzy duplicate detection (Plan step 12).

Definition (spec): same from_address + same normalized subject + body similarity
>= threshold (rapidfuzz fuzz.ratio). In each duplicate group the earliest email
is the original; every later member is flagged with is_duplicate = 1,
duplicate_of = <original message_id> and its similarity_score to the original.

Method:
  * Candidates: rows with is_copy = 0 (folder copies, then timezone-shifted
    copies, were collapsed first; see pipeline/copies.py).
  * Comparison text: normalize_for_similarity(body); if under min_chars, the
    normalized forwarded_content instead; if that is also short or missing,
    the email is excluded. Stored body/forwarded_content are never modified.
  * Blocks: (from_address, normalized_subject).
  * Order inside a block: (bogus_date, date, source_file) - plausible dates
    first, then time, then path. This order is the tie-break everywhere.
  * Anchor grouping: walk the block in that order; each email is compared with
    the anchor (first, earliest member) of every existing group and joins the
    group with the highest score >= threshold (equal scores: the earlier
    anchor). Otherwise it starts a new group as its anchor.
  * Bogus dates (outside [PLAUSIBLE_START, PLAUSIBLE_END)) sort after all
    plausible dates, so they are never chosen as originals while a plausible
    member exists. In an all-bogus group the anchor falls back to source_file
    order.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from pipeline.parsing.body import normalize_for_similarity

PLAUSIBLE_START = "1997-01-01T00:00:00Z"
PLAUSIBLE_END = "2003-01-01T00:00:00Z"
EXCLUDED_NO_FORWARD = "short_primary_no_forwarded"
EXCLUDED_SHORT_FORWARD = "short_primary_short_forwarded"


def is_bogus_date(date: str) -> bool:
    return not (PLAUSIBLE_START <= date < PLAUSIBLE_END)


def comparison_text(body: str | None, forwarded: str | None, min_chars: int) -> tuple[str | None, str]:
    """(text, source) where source is 'primary', 'forwarded' or an exclusion reason."""
    primary = normalize_for_similarity(body)
    if len(primary) >= min_chars:
        return primary, "primary"
    fwd = normalize_for_similarity(forwarded)
    if len(fwd) >= min_chars:
        return fwd, "forwarded"
    return None, EXCLUDED_SHORT_FORWARD if fwd else EXCLUDED_NO_FORWARD


def similarity(a: str, b: str, threshold: float) -> float | None:
    """fuzz.ratio if >= threshold, else None. Skips pairs whose lengths make the threshold unreachable."""
    la, lb = len(a), len(b)
    if 200.0 * min(la, lb) / (la + lb) < threshold:
        return None
    score = fuzz.ratio(a, b, score_cutoff=threshold)
    return score if score >= threshold else None


@dataclass
class Candidate:
    id: int
    message_id: str
    source_file: str
    date: str
    text: str
    bogus: bool

    @property
    def order(self) -> tuple:
        return (self.bogus, self.date, self.source_file)


@dataclass
class Group:
    anchor: Candidate
    members: list[tuple[Candidate, float]] = field(default_factory=list)


@dataclass
class DedupStats:
    threshold: float = 90.0
    min_chars: int = 20
    candidates: int = 0                # non-copy emails considered
    eligible: int = 0                  # candidates with a comparison text
    used_forwarded: int = 0            # eligible via the forwarded_content fallback
    excluded: Counter = field(default_factory=Counter)
    blocks_compared: int = 0           # blocks with 2+ eligible emails
    groups: int = 0                    # duplicate groups (original + 1 or more flagged)
    flagged: int = 0
    largest_group: int = 0
    bogus_dates: int = 0               # candidates with an implausible date
    bogus_in_groups: int = 0           # of those, members of a duplicate group (never the original)
    bogus_only_groups: int = 0         # groups whose members are all bogus (source_file fallback)

    @property
    def avg_group_size(self) -> float:
        """Mean emails per duplicate group, counting the original. Denominator: duplicate groups."""
        return round((self.flagged + self.groups) / self.groups, 2) if self.groups else 0.0

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold, "min_chars": self.min_chars,
            "candidates_after_copy_collapse": self.candidates, "eligible": self.eligible,
            "eligible_via_forwarded_fallback": self.used_forwarded,
            "excluded": dict(self.excluded), "blocks_compared": self.blocks_compared,
            "duplicate_groups": self.groups, "flagged": self.flagged,
            "avg_group_size_incl_original": self.avg_group_size, "largest_group": self.largest_group,
            "bogus_dates": self.bogus_dates, "bogus_in_groups": self.bogus_in_groups,
            "bogus_only_groups": self.bogus_only_groups,
        }

    def format(self) -> str:
        lines = [
            f"Duplicate detection (fuzz.ratio >= {self.threshold:g}, comparison text >= {self.min_chars} chars)",
            f"  emails after copy collapse   {self.candidates:>7,}",
            f"  eligible for comparison      {self.eligible:>7,}  ({self.used_forwarded:,} via forwarded_content fallback)",
        ]
        for reason, n in self.excluded.most_common():
            lines.append(f"  excluded: {reason:<30} {n:>5,}")
        lines += [
            f"  blocks with 2+ eligible      {self.blocks_compared:>7,}",
            f"  duplicate groups             {self.groups:>7,}",
            f"  emails flagged               {self.flagged:>7,}",
            f"  avg group size (incl. orig.) {self.avg_group_size:>7}   largest {self.largest_group}",
            f"  bogus dates: {self.bogus_dates} candidates, {self.bogus_in_groups} in duplicate groups "
            f"(sorted last, never original), {self.bogus_only_groups} all-bogus groups (source_file fallback)",
        ]
        return "\n".join(lines)


def detect_duplicates(conn: sqlite3.Connection, threshold: float = 90.0, min_chars: int = 20) -> DedupStats:
    """Recompute duplicate flags from scratch. Notification columns are left untouched."""
    stats = DedupStats(threshold=threshold, min_chars=min_chars)
    rows = conn.execute(
        """SELECT id, message_id, from_address, normalized_subject, date, source_file, body, forwarded_content
           FROM emails WHERE is_copy = 0""").fetchall()
    stats.candidates = len(rows)

    blocks: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for row_id, mid, sender, nsubj, date, source, body, fwd in rows:
        bogus = is_bogus_date(date)
        stats.bogus_dates += bogus
        text, source_kind = comparison_text(body, fwd, min_chars)
        if text is None:
            stats.excluded[source_kind] += 1
            continue
        stats.eligible += 1
        stats.used_forwarded += source_kind == "forwarded"
        blocks[(sender, nsubj)].append(Candidate(row_id, mid, source, date, text, bogus))

    updates = []
    for key in sorted(blocks):
        block = blocks[key]
        if len(block) < 2:
            continue
        stats.blocks_compared += 1
        groups: list[Group] = []
        for cand in sorted(block, key=lambda c: c.order):
            best: tuple[Group, float] | None = None
            for g in groups:
                score = similarity(cand.text, g.anchor.text, threshold)
                if score is not None and (best is None or score > best[1]):
                    best = (g, score)
            if best:
                best[0].members.append((cand, best[1]))
            else:
                groups.append(Group(anchor=cand))
        for g in groups:
            if not g.members:
                continue
            stats.groups += 1
            stats.flagged += len(g.members)
            stats.largest_group = max(stats.largest_group, len(g.members) + 1)
            stats.bogus_in_groups += sum(c.bogus for c, _ in g.members) + g.anchor.bogus
            stats.bogus_only_groups += g.anchor.bogus  # anchor bogus => every member bogus
            updates += [(g.anchor.message_id, round(score, 2), c.id) for c, score in g.members]

    with conn:
        conn.execute("UPDATE emails SET is_duplicate = 0, duplicate_of = NULL, similarity_score = NULL")
        conn.executemany(
            "UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = ? WHERE id = ?", updates)
    return stats


def run_dedup(config) -> tuple:
    """Stages S6-S8 on an existing database: collapse copies, detect, write the report."""
    from pipeline.copies import collapse_copies, collapse_tz_shifted
    from pipeline.db import connect, init_schema
    from pipeline.report import write_report

    conn = connect(config.db)
    init_schema(conn)
    copy_stats = collapse_copies(conn, config.dedup_mode)
    tz_stats = None
    if config.dedup_mode == "collapse" and config.tz_collapse:
        tz_stats = collapse_tz_shifted(conn)
    dedup_stats = detect_duplicates(conn, config.threshold, config.min_body_chars)
    rows = write_report(conn, config.report)
    out = Path(config.output_dir) / "dedup_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"copy_collapse": vars(copy_stats),
                               "tz_shift_collapse": vars(tz_stats) if tz_stats else None,
                               "dedup": dedup_stats.to_dict(), "report_rows": rows}, indent=2) + "\n")
    conn.close()
    return copy_stats, tz_stats, dedup_stats, rows


def main(argv: list[str] | None = None) -> int:
    from config import parse_args

    copy_stats, tz_stats, dedup_stats, rows = run_dedup(parse_args(argv))
    print(copy_stats.format())
    print(tz_stats.format() if tz_stats else "Timezone-shifted copy stage: disabled")
    print(dedup_stats.format())
    print(f"duplicates_report.csv: {rows:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
