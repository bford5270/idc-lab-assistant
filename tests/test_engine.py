"""Tests for engine.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import (
    URGENCY_BY_SEVERITY,
    evaluate,
    find_severity,
    load_rules,
    pick_thresholds,
    render_follow_up,
    render_template,
)


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


# ---------- find_severity ----------


def test_find_severity_normal_band():
    thresholds = [
        {"severity": "Low", "max": 3.0},
        {"severity": "Normal", "min": 3.0, "max": 5.0},
        {"severity": "High", "min": 5.0},
    ]
    assert find_severity(4.0, thresholds) == "Normal"


def test_find_severity_inclusive_low_boundary():
    thresholds = [
        {"severity": "Normal", "min": 3.5, "max": 5.0},
        {"severity": "Mild High", "min": 5.0, "max": 5.5},
    ]
    # value at exact lower bound goes to the higher tier (inclusive low).
    assert find_severity(5.0, thresholds) == "Mild High"


def test_find_severity_exclusive_high_boundary():
    thresholds = [
        {"severity": "Normal", "min": 3.5, "max": 5.0},
        {"severity": "Mild High", "min": 5.0, "max": 5.5},
    ]
    # value just below upper bound stays in lower tier (exclusive high).
    assert find_severity(4.99, thresholds) == "Normal"


def test_find_severity_open_low():
    thresholds = [{"severity": "Critical Low", "max": 2.5}]
    assert find_severity(1.0, thresholds) == "Critical Low"


def test_find_severity_open_high():
    thresholds = [{"severity": "Critical High", "min": 7.0}]
    assert find_severity(8.0, thresholds) == "Critical High"


def test_find_severity_unknown_outside_all_bands():
    thresholds = [{"severity": "Normal", "min": 3.5, "max": 5.0}]
    assert find_severity(10.0, thresholds) == "Unknown"
    assert find_severity(0.0, thresholds) == "Unknown"


# ---------- pick_thresholds ----------


def test_pick_thresholds_static_returns_thresholds(rules):
    lab = rules["labs"]["potassium"]
    thresholds, used_default = pick_thresholds(lab, None)
    assert thresholds is lab["thresholds"]
    assert used_default is False


def test_pick_thresholds_sex_provided_uses_sex_bands(rules):
    lab = rules["labs"]["hemoglobin"]
    thresholds, used_default = pick_thresholds(lab, {"sex": "female"})
    assert thresholds is lab["thresholds_by_context"]["female"]
    assert used_default is False


def test_pick_thresholds_no_context_falls_back_to_default_with_flag(rules):
    lab = rules["labs"]["hemoglobin"]
    thresholds, used_default = pick_thresholds(lab, None)
    assert thresholds is lab["thresholds_by_context"]["default"]
    assert used_default is True


def test_pick_thresholds_unrecognized_sex_falls_back_to_default(rules):
    lab = rules["labs"]["hemoglobin"]
    thresholds, used_default = pick_thresholds(lab, {"sex": "unspecified"})
    assert thresholds is lab["thresholds_by_context"]["default"]
    assert used_default is True


# ---------- render_template ----------


def test_render_template_substitutes_known_slots():
    out = render_template("K = {value} {unit}", {"value": 6.2, "unit": "mEq/L"})
    assert out == "K = 6.2 mEq/L"


def test_render_template_leaves_unknown_slots():
    out = render_template("foo {bar}", {})
    assert out == "foo {bar}"


def test_render_template_leaves_bracket_placeholders():
    out = render_template("ECG: [findings]. K = {value}", {"value": 6.2})
    assert out == "ECG: [findings]. K = 6.2"


def test_render_template_skips_none_values():
    out = render_template("age = {age}", {"age": None})
    assert out == "age = {age}"


def test_render_template_handles_empty_slot_dict():
    out = render_template("x = {x}", {})
    assert out == "x = {x}"


def test_render_follow_up_renders_all_fields():
    follow_up = {
        "category": "Severe X",
        "next_tests": ["Repeat {value}.", "ECG."],
        "ehr_plan": "Value = {value} {unit}.",
        "patient_communication": "Your value is {value}.",
    }
    out = render_follow_up(follow_up, {"value": 7.5, "unit": "mEq/L"})
    assert out["category"] == "Severe X"
    assert out["next_tests"] == ["Repeat 7.5.", "ECG."]
    assert out["ehr_plan"] == "Value = 7.5 mEq/L."
    assert out["patient_communication"] == "Your value is 7.5."


# ---------- evaluate ----------


def test_evaluate_potassium_critical_high(rules):
    result = evaluate("potassium", 7.5, rules)
    assert result["severity"] == "Critical High"
    assert result["follow_up"]["category"].startswith("Critical hyperkalemia")
    assert "7.5" in result["follow_up"]["ehr_plan"]


def test_evaluate_potassium_normal_has_no_follow_up(rules):
    result = evaluate("potassium", 4.0, rules)
    assert result["severity"] == "Normal"
    assert result["follow_up"] is None


def test_evaluate_unknown_lab_returns_error(rules):
    result = evaluate("unobtainium", 1.0, rules)
    assert "error" in result


def test_evaluate_creatinine_includes_differentiation(rules):
    result = evaluate("creatinine", 2.5, rules, {"sex": "male"})
    assert result["differentiation"] is not None
    assert len(result["differentiation"]["reasoning_prompts"]) >= 1


def test_evaluate_hemoglobin_default_flagged_when_no_sex(rules):
    result = evaluate("hemoglobin", 10.0, rules, None)
    assert result["threshold_used_default"] is True


def test_evaluate_hemoglobin_female_not_flagged(rules):
    result = evaluate("hemoglobin", 10.0, rules, {"sex": "female"})
    assert result["threshold_used_default"] is False


def test_evaluate_potassium_boundary_5_0_is_mild_high(rules):
    """[min, max) — K=5.0 inclusive low, so it lands in Mild High not Normal."""
    assert evaluate("potassium", 5.0, rules)["severity"] == "Mild High"


def test_evaluate_potassium_boundary_below_normal_upper(rules):
    """K=4.99 exclusive high — stays in Normal."""
    assert evaluate("potassium", 4.99, rules)["severity"] == "Normal"


# ---------- urgency map ----------


def test_urgency_map_covers_all_ladder_levels():
    expected = {
        "Critical Low",
        "Critical High",
        "Severe Low",
        "Severe High",
        "Moderate Low",
        "Moderate High",
        "Mild Low",
        "Mild High",
        "Normal",
        "Unknown",
    }
    assert expected.issubset(URGENCY_BY_SEVERITY.keys())


# ---------- rules.json schema integrity ----------


def test_all_labs_have_required_fields(rules):
    for lab_id, lab_def in rules["labs"].items():
        assert "display_name" in lab_def, f"{lab_id} missing display_name"
        assert "synonyms" in lab_def, f"{lab_id} missing synonyms"
        assert "unit" in lab_def, f"{lab_id} missing unit"
        assert "thresholds" in lab_def or "thresholds_by_context" in lab_def, \
            f"{lab_id} missing thresholds"


def test_every_threshold_has_severity(rules):
    for lab_id, lab_def in rules["labs"].items():
        if "thresholds" in lab_def:
            for t in lab_def["thresholds"]:
                assert "severity" in t, f"{lab_id} threshold missing severity"
        else:
            for ctx, ctx_thresholds in lab_def["thresholds_by_context"].items():
                for t in ctx_thresholds:
                    assert "severity" in t, f"{lab_id}[{ctx}] threshold missing severity"


def test_every_severity_in_follow_up_is_valid(rules):
    """Severity keys in follow_up must be in the canonical ladder."""
    valid = set(URGENCY_BY_SEVERITY.keys())
    for lab_id, lab_def in rules["labs"].items():
        for severity in lab_def.get("follow_up", {}):
            assert severity in valid, f"{lab_id} has unexpected severity {severity!r}"
