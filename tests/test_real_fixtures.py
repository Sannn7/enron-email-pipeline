"""Real-email fixtures vs tests/fixtures/expected/*.json (one test per fixture).

Set fixtures (dedup / thread groups) are only checked at the parse level here;
their group-level expectations are tested in the dedup and thread steps.
"""
import json
from pathlib import Path

import pytest

from pipeline.extract import extract_file
from pipeline.models import EmailRecord
from pipeline.parsing.body import normalize_for_similarity

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = sorted((FIXTURES / "expected").glob("*.json"))
MEMBER_FIELDS = ("message_id", "date", "from_address", "subject")


def resolve(source_file: str) -> Path:
    for base in ("real", "synthetic"):
        p = FIXTURES / base / source_file
        if p.exists():
            return p
    raise FileNotFoundError(source_file)


def check_text(label, actual, expected, problems):
    if expected is None:
        if actual is not None:
            problems.append(f"{label}: expected None, got {actual[:60]!r}")
        return
    if isinstance(expected, str):
        if actual != expected:
            problems.append(f"{label}: expected exact {expected[:60]!r}, got {(actual or '')[:60]!r}")
        return
    if actual is None:
        problems.append(f"{label}: expected text starting {expected['starts_with'][:40]!r}, got None")
        return
    actual = actual.strip()
    if not actual.startswith(expected["starts_with"]):
        problems.append(f"{label}.starts_with: expected {expected['starts_with'][:50]!r}, got {actual[:50]!r}")
    if not actual.endswith(expected["ends_with"]):
        problems.append(f"{label}.ends_with: expected {expected['ends_with'][-50:]!r}, got {actual[-50:]!r}")
    if len(actual) != expected["length"]:
        problems.append(f"{label}.length: expected {expected['length']}, got {len(actual)}")


def check_status(exp, result, problems, label=""):
    if exp["status"] == "ok":
        if not isinstance(result, EmailRecord):
            problems.append(f"{label}status: expected ok, got failure {result.reason} ({result.detail})")
            return False
        return True
    if isinstance(result, EmailRecord):
        problems.append(f"{label}status: expected failure {exp['failure_reason']}, got ok")
    elif result.reason != exp["failure_reason"]:
        problems.append(f"{label}failure_reason: expected {exp['failure_reason']}, got {result.reason}")
    return False


@pytest.mark.parametrize("exp_path", EXPECTED, ids=lambda p: p.stem)
def test_fixture(exp_path):
    exp = json.loads(exp_path.read_text())
    problems: list[str] = []

    if "members" in exp:
        for m in exp["members"]:
            r = extract_file(resolve(m["source_file"]), m["source_file"])
            tag = m["source_file"].split("maildir/")[1] + ": "
            if check_status(m, r, problems, tag):
                for f in MEMBER_FIELDS:
                    if getattr(r, f) != m[f]:
                        problems.append(f"{tag}{f}: expected {m[f]!r}, got {getattr(r, f)!r}")
                plen = len(normalize_for_similarity(r.body))
                if plen != m["primary_body_len"]:
                    problems.append(f"{tag}primary_body_len: expected {m['primary_body_len']}, got {plen}")
    else:
        fields = exp.get("fields", {})
        source = fields.get("source_file") or exp["fields_present_in_raw"]["source_file"]
        r = extract_file(resolve(source), source)
        if check_status(exp, r, problems):
            for name, want in fields.items():
                got = getattr(r, name)
                if got != want:
                    problems.append(f"{name}: expected {str(want)[:90]!r}, got {str(got)[:90]!r}")
            check_text("body", r.body, exp["body"], problems)
            check_text("forwarded_content", r.forwarded_content, exp["forwarded_content"], problems)
            check_text("quoted_content", r.quoted_content, exp["quoted_content"], problems)

    assert not problems, f"{exp['fixture_id']} ({exp['category']}):\n  " + "\n  ".join(problems)
