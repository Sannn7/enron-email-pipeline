"""Extraction statistics and field completeness (Plan step 10)."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.models import EmailRecord, ParseFailure

# Spec fields (mandatory first, then optional), plus the two thread headers.
MANDATORY_FIELDS = ["message_id", "date", "from_address", "to_addresses", "subject", "body", "source_file"]
OPTIONAL_FIELDS = ["cc_addresses", "bcc_addresses", "x_from", "x_to", "x_cc", "x_bcc", "x_folder",
                   "x_origin", "content_type", "has_attachment", "forwarded_content", "quoted_content",
                   "in_reply_to", "references"]
FIELDS = MANDATORY_FIELDS + OPTIONAL_FIELDS


def _present(value) -> bool:
    """A field counts as present when it is non-empty (has_attachment: when True)."""
    if isinstance(value, bool):
        return value
    return value is not None and value != "" and value != []


@dataclass
class ExtractionStats:
    found: int = 0
    parsed: int = 0
    failed: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    failure_reasons: Counter = field(default_factory=Counter)
    present_counts: Counter = field(default_factory=Counter)

    def add_record(self, record: EmailRecord) -> None:
        self.parsed += 1
        for name in FIELDS:
            if _present(getattr(record, name)):
                self.present_counts[name] += 1

    def add_failure(self, failure: ParseFailure) -> None:
        self.failed += 1
        self.failure_reasons[failure.reason] += 1

    def completeness(self) -> dict[str, float]:
        """Percent of successfully parsed emails in which each field is present."""
        if not self.parsed:
            return {name: 0.0 for name in FIELDS}
        return {name: round(100 * self.present_counts[name] / self.parsed, 1) for name in FIELDS}

    def to_dict(self) -> dict:
        return {
            "files_found": self.found,
            "parsed": self.parsed,
            "failed": self.failed,
            "inserted": self.inserted,
            "skipped_existing": self.skipped_existing,
            "failure_reasons": dict(self.failure_reasons.most_common()),
            "field_completeness_pct": self.completeness(),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    def format(self) -> str:
        pct = lambda n: f"{100 * n / self.found:.1f}%" if self.found else "0.0%"
        lines = [
            "Extraction statistics",
            f"  files found        {self.found:>8,}",
            f"  parsed OK          {self.parsed:>8,}  ({pct(self.parsed)})",
            f"  failed             {self.failed:>8,}  ({pct(self.failed)})",
            f"  inserted into DB   {self.inserted:>8,}",
            f"  skipped (existing) {self.skipped_existing:>8,}",
        ]
        if self.failure_reasons:
            lines.append("  failure reasons:")
            lines += [f"    {reason:<20} {n:>6,}" for reason, n in self.failure_reasons.most_common()]
        lines.append("Field completeness (% of parsed emails)")
        comp = self.completeness()
        for name in FIELDS:
            tag = "*" if name in MANDATORY_FIELDS else " "
            lines.append(f"  {tag} {name:<18} {comp[name]:>6.1f}%")
        lines.append("  (* = mandatory)")
        return "\n".join(lines)
