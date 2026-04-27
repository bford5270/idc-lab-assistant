"""Tests for lab_parser.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import load_rules
from lab_parser import _match_lab_id, parse_text


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


# ---------- parse_text ----------


def test_parse_single_line(rules):
    parsed = parse_text("K 6.2", rules)
    assert len(parsed) == 1
    assert parsed[0].lab_id == "potassium"
    assert parsed[0].value == 6.2


def test_parse_multiple_lines(rules):
    parsed = parse_text("K 6.2\nNa 138\nGlucose 320", rules)
    assert {p.lab_id for p in parsed} == {"potassium", "sodium", "glucose"}


def test_parse_ignores_unknown_labs(rules):
    parsed = parse_text("UnknownLab 42\nK 4.0", rules)
    assert len(parsed) == 1
    assert parsed[0].lab_id == "potassium"


def test_parse_handles_synonyms(rules):
    parsed = parse_text("Potassium 4.5", rules)
    assert parsed[0].lab_id == "potassium"
    parsed = parse_text("hgb 14.0", rules)
    assert parsed[0].lab_id == "hemoglobin"
    parsed = parse_text("creat 1.2", rules)
    assert parsed[0].lab_id == "creatinine"


def test_parse_decimal_and_integer_values(rules):
    parsed = parse_text("Cr 1.5\nGlucose 200", rules)
    by_lab = {p.lab_id: p.value for p in parsed}
    assert by_lab["creatinine"] == 1.5
    assert by_lab["glucose"] == 200.0


def test_parse_empty_input(rules):
    assert parse_text("", rules) == []
    assert parse_text("\n\n   \n", rules) == []


def test_parse_skips_lines_without_numbers(rules):
    parsed = parse_text("K is high\nNa 138", rules)
    # 'K is high' has no numeric value — skipped.
    assert len(parsed) == 1
    assert parsed[0].lab_id == "sodium"


# ---------- _match_lab_id (word-boundary semantics) ----------


def test_match_word_boundary_avoids_substring(rules):
    """Synonym 'k' must not match inside other words (e.g. 'ankylosis')."""
    assert _match_lab_id("ankylosis 5", rules) is None


def test_match_full_synonym_in_line(rules):
    assert _match_lab_id("Sodium 138 mEq/L", rules) == "sodium"
    assert _match_lab_id("Hemoglobin 14.0 g/dL", rules) == "hemoglobin"


def test_match_short_synonym(rules):
    assert _match_lab_id("hb 14", rules) == "hemoglobin"
    assert _match_lab_id("k 4.5", rules) == "potassium"


def test_match_returns_none_when_no_synonym_matches(rules):
    assert _match_lab_id("foo bar baz", rules) is None
