"""Tests for the Hep B serology interpreter (engine.evaluate_serology).

The fixture rules contain a small synthetic serology lab so the test
suite doesn't depend on the exact pattern bookkeeping in the production
rules.json — but a couple of end-to-end tests do exercise the real
hepatitis_b_serology entry to confirm the schema there matches what
the interpreter expects.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import evaluate_serology, load_rules


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


# ---------- Hep B pattern matching ----------


def _hep_b(rules: dict, **markers) -> dict:
    """Helper — markers can be True/False/None, missing keys default to None."""
    inputs = {
        "hbsag": markers.get("hbsag"),
        "anti_hbs": markers.get("anti_hbs"),
        "anti_hbc_total": markers.get("anti_hbc_total"),
        "anti_hbc_igm": markers.get("anti_hbc_igm"),
    }
    return evaluate_serology("hepatitis_b_serology", inputs, rules)


def test_hep_b_susceptible(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=False, anti_hbc_igm=False)
    assert r["pattern_id"] == "susceptible"
    assert r["missing_inputs"] == []


def test_hep_b_vaccinated(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=True, anti_hbc_total=False, anti_hbc_igm=False)
    assert r["pattern_id"] == "vaccinated"


def test_hep_b_resolved_past_infection(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=True, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "resolved_infection"


def test_hep_b_acute_infection(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    assert r["pattern_id"] == "acute_infection"
    assert "acute" in r["category"].lower()


def test_hep_b_chronic_infection(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "chronic_infection"
    assert "hcc" in r["ehr_plan"].lower() or "hepatocellular" in r["ehr_plan"].lower()


def test_hep_b_window_period(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    assert r["pattern_id"] == "window_period"


def test_hep_b_lone_anti_hbc(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "lone_anti_hbc"


def test_hep_b_indeterminate_atypical(rules):
    """HBsAg+ + anti-HBs+ simultaneously is atypical — falls through to
    the indeterminate fallback."""
    r = _hep_b(rules, hbsag=True, anti_hbs=True, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "indeterminate"


# ---------- Missing-input handling ----------


def test_hep_b_partial_inputs_lists_missing(rules):
    """Only HBsAg + anti-HBs available — anti_hbc markers absent. The
    matcher requires all four, so falls to indeterminate, but the
    missing_inputs list helps the IDC see what's needed."""
    r = _hep_b(rules, hbsag=False, anti_hbs=True)
    assert set(r["missing_inputs"]) == {"anti_hbc_total", "anti_hbc_igm"}


def test_hep_b_no_inputs_falls_back_to_indeterminate(rules):
    r = evaluate_serology("hepatitis_b_serology", {}, rules)
    assert r["pattern_id"] == "indeterminate"
    assert len(r["missing_inputs"]) == 4


# ---------- Result shape + sources ----------


def test_hep_b_result_includes_paste_ready_blocks(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    # Acute pattern fully populated
    assert r["ehr_plan"]
    assert r["patient_communication"]
    assert r["next_tests"]
    assert r["display_name"] == "Hepatitis B Serology"
    assert r["kind"] == "serology"


def test_hep_b_result_includes_sources(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=False, anti_hbc_igm=False)
    assert any("CDC" in s for s in r["sources"])


# ---------- error path ----------


def test_evaluate_serology_rejects_non_serology_lab(rules):
    """Calling with a numeric lab returns an error, not a pattern."""
    r = evaluate_serology("potassium", {"hbsag": True}, rules)
    assert "error" in r
    assert "not a serology lab" in r["error"].lower()


def test_evaluate_serology_unknown_lab(rules):
    r = evaluate_serology("nope_not_a_lab", {}, rules)
    assert "error" in r
