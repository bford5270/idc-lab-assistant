"""Parser for free-text EHR lab data.

Pure module — no Streamlit imports. Testable independently. Named
`lab_parser` to avoid colliding with any historical stdlib `parser` module.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class ParsedLab(NamedTuple):
    lab_id: str
    value: float
    raw_line: str


_NUMBER_PATTERN = re.compile(r"-?\d{1,4}(?:,\d{3})*(?:\.\d+)?")


def parse_text(text: str, rules: dict) -> list[ParsedLab]:
    """Parse free-text EHR lab data into a list of ParsedLab tuples.

    Strategy: split into lines; for each line, find the best lab synonym
    match and pair it with the first numeric value on that line. Longest
    synonym wins to avoid short-substring false positives (e.g. 'hgb' beats
    'hb' if both could match).

    Limitations (Phase 1 — refined in later commits):
    - Multiple labs on a single line aren't split (e.g. 'K 4.5 Na 138').
    - Doesn't normalize SI units.
    """
    results: list[ParsedLab] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lab_id = _match_lab_id(line, rules)
        if lab_id is None:
            continue

        numbers = _NUMBER_PATTERN.findall(line)
        if not numbers:
            continue

        try:
            value = float(numbers[0].replace(",", ""))
        except ValueError:
            continue

        results.append(ParsedLab(lab_id=lab_id, value=value, raw_line=raw_line))

    return results


def _match_lab_id(line: str, rules: dict) -> str | None:
    """Return the lab_id whose synonym best matches the line, or None.

    Word-boundary matching avoids substring false positives. When multiple
    labs match (e.g. 'hemoglobin' and 'hb' both fire on 'hemoglobin 14.0'),
    the longest synonym wins.
    """
    line_lower = line.lower()
    candidates: list[tuple[int, str]] = []

    for lab_id, lab_def in rules.get("labs", {}).items():
        for synonym in lab_def.get("synonyms", []):
            pattern = r"\b" + re.escape(synonym.lower()) + r"\b"
            if re.search(pattern, line_lower):
                candidates.append((len(synonym), lab_id))
                break

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
