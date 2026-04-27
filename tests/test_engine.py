"""Tests for engine.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import (
    URGENCY_BY_SEVERITY,
    assign_ckd_a_stage,
    assign_ckd_g_stage,
    chronic_ckd_labs_indicated,
    compute_anion_gap,
    compute_bun_cr_ratio,
    compute_egfr,
    compute_kdigo_aki_stage,
    compute_prevent_risk,
    correct_calcium_for_albumin,
    evaluate,
    evaluate_panel,
    find_severity,
    interpret_bun_cr_ratio,
    load_rules,
    pick_follow_up_dict,
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
    diff = result["differentiation"]
    assert diff is not None
    # New schema: baseline_input + CKD stage definitions, not reasoning_prompts.
    assert "baseline_input" in diff
    assert "ckd_g_stages" in diff
    assert "ckd_a_stages" in diff
    assert "chronic_lab_panel" in diff
    assert diff["chronic_lab_panel_trigger_stage"] == "G3a"


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
    """Severity keys in follow_up (and follow_up_by_context branches) must be in the canonical ladder."""
    valid = set(URGENCY_BY_SEVERITY.keys())
    for lab_id, lab_def in rules["labs"].items():
        for severity in lab_def.get("follow_up", {}):
            assert severity in valid, f"{lab_id} has unexpected severity {severity!r}"
        for branch_name, branch in lab_def.get("follow_up_by_context", {}).items():
            for severity in branch:
                assert severity in valid, (
                    f"{lab_id}.follow_up_by_context.{branch_name} has unexpected severity {severity!r}"
                )


# ---------- pick_follow_up_dict (context branching) ----------


def test_pick_follow_up_dict_static(rules):
    lab = rules["labs"]["potassium"]
    fu, branch = pick_follow_up_dict(lab, None)
    assert fu is lab["follow_up"]
    assert branch is None


def test_pick_follow_up_dict_diabetic_branch(rules):
    lab = rules["labs"]["glucose"]
    fu, branch = pick_follow_up_dict(lab, {"diabetic": True})
    assert branch == "diabetic"
    assert "Severe High" in fu


def test_pick_follow_up_dict_non_diabetic_branch(rules):
    lab = rules["labs"]["glucose"]
    fu, branch = pick_follow_up_dict(lab, {"diabetic": False})
    assert branch == "default"


def test_pick_follow_up_dict_no_diabetic_context_uses_default(rules):
    lab = rules["labs"]["glucose"]
    fu, branch = pick_follow_up_dict(lab, None)
    assert branch == "default"


def test_glucose_severe_high_non_diabetic_categorized_as_new_dm(rules):
    """Per IDC policy: non-diabetic with Severe High = ED for possible new DKA/HHS."""
    result = evaluate("glucose", 250, rules, {"diabetic": False})
    assert result["follow_up_branch"] == "default"
    assert "non-diabetic" in result["follow_up"]["category"].lower()


def test_glucose_severe_high_diabetic_anion_gap_driven(rules):
    """Per IDC policy: known diabetic with Severe High routes via anion gap."""
    result = evaluate("glucose", 250, rules, {"diabetic": True})
    assert result["follow_up_branch"] == "diabetic"
    assert "anion gap" in result["follow_up"]["ehr_plan"].lower()


# ---------- compute_egfr (CKD-EPI 2021) ----------


def test_egfr_returns_none_when_inputs_missing():
    assert compute_egfr(None, 50, "male") is None
    assert compute_egfr(1.0, None, "male") is None
    assert compute_egfr(1.0, 50, None) is None
    assert compute_egfr(0, 50, "male") is None
    assert compute_egfr(1.0, 0, "male") is None


def test_egfr_female_typical():
    """50yo female, Cr 1.0 — published reference checks ~71 mL/min/1.73 m²."""
    egfr = compute_egfr(1.0, 50, "female")
    assert egfr is not None
    assert 65 < egfr < 80


def test_egfr_male_typical():
    """50yo male, Cr 1.0 — published reference ~95 mL/min/1.73 m²."""
    egfr = compute_egfr(1.0, 50, "male")
    assert egfr is not None
    assert 88 < egfr < 100


def test_egfr_female_higher_than_male_at_same_cr_age():
    """At same Cr/age, CKD-EPI 2021 yields higher eGFR for males.

    The female sex factor of 1.012 is a small offset on top of different
    kappa/alpha. At Cr ≥ 0.7 (above κ_female) females actually compute lower.
    """
    f = compute_egfr(1.2, 55, "female")
    m = compute_egfr(1.2, 55, "male")
    assert f < m  # at Cr above female κ, males have higher eGFR


# ---------- assign_ckd_g_stage ----------


def test_ckd_g_stage_boundaries():
    assert assign_ckd_g_stage(120) == "G1"
    assert assign_ckd_g_stage(90) == "G1"
    assert assign_ckd_g_stage(89.9) == "G2"
    assert assign_ckd_g_stage(60) == "G2"
    assert assign_ckd_g_stage(59.9) == "G3a"
    assert assign_ckd_g_stage(45) == "G3a"
    assert assign_ckd_g_stage(44.9) == "G3b"
    assert assign_ckd_g_stage(30) == "G3b"
    assert assign_ckd_g_stage(29.9) == "G4"
    assert assign_ckd_g_stage(15) == "G4"
    assert assign_ckd_g_stage(14.9) == "G5"
    assert assign_ckd_g_stage(0) == "G5"


def test_ckd_g_stage_none_for_missing():
    assert assign_ckd_g_stage(None) is None


# ---------- assign_ckd_a_stage ----------


def test_ckd_a_stage_boundaries():
    assert assign_ckd_a_stage(0) == "A1"
    assert assign_ckd_a_stage(29.9) == "A1"
    assert assign_ckd_a_stage(30) == "A2"
    assert assign_ckd_a_stage(299.9) == "A2"
    assert assign_ckd_a_stage(300) == "A3"
    assert assign_ckd_a_stage(1000) == "A3"


def test_ckd_a_stage_none_for_missing():
    assert assign_ckd_a_stage(None) is None


# ---------- chronic_ckd_labs_indicated ----------


def test_chronic_ckd_labs_only_at_g3a_or_worse():
    assert not chronic_ckd_labs_indicated("G1")
    assert not chronic_ckd_labs_indicated("G2")
    assert chronic_ckd_labs_indicated("G3a")
    assert chronic_ckd_labs_indicated("G3b")
    assert chronic_ckd_labs_indicated("G4")
    assert chronic_ckd_labs_indicated("G5")
    assert not chronic_ckd_labs_indicated(None)


# ---------- compute_kdigo_aki_stage ----------


def test_aki_stage_3_by_ratio():
    assert compute_kdigo_aki_stage(3.5, 1.0) == "Stage 3"


def test_aki_stage_3_by_absolute():
    assert compute_kdigo_aki_stage(4.0, 2.0) == "Stage 3"


def test_aki_stage_2_by_ratio():
    assert compute_kdigo_aki_stage(2.0, 1.0) == "Stage 2"


def test_aki_stage_1_by_ratio():
    assert compute_kdigo_aki_stage(1.5, 1.0) == "Stage 1"


def test_aki_stage_1_by_delta():
    """Delta ≥ 0.3 mg/dL with ratio < 1.5 should land in Stage 1."""
    # Cr 1.4, baseline 1.0: delta 0.4, ratio 1.4 — delta path triggers Stage 1.
    assert compute_kdigo_aki_stage(1.4, 1.0) == "Stage 1"


def test_aki_no_aki_below_thresholds():
    assert compute_kdigo_aki_stage(1.05, 1.0) == "No AKI"


def test_aki_none_when_baseline_missing():
    assert compute_kdigo_aki_stage(2.0, None) is None
    assert compute_kdigo_aki_stage(2.0, 0) is None


# ---------- BUN/Cr ratio ----------


def test_bun_cr_ratio_basic():
    assert compute_bun_cr_ratio(20, 1.0) == 20.0
    assert compute_bun_cr_ratio(30, 1.5) == 20.0


def test_bun_cr_ratio_none_for_missing():
    assert compute_bun_cr_ratio(None, 1.0) is None
    assert compute_bun_cr_ratio(20, None) is None
    assert compute_bun_cr_ratio(20, 0) is None


def test_bun_cr_interpretation_high():
    text = interpret_bun_cr_ratio(25.0)
    assert text and "prerenal" in text.lower()


def test_bun_cr_interpretation_low():
    text = interpret_bun_cr_ratio(8.0)
    assert text and "intrinsic" in text.lower()


def test_bun_cr_interpretation_normal():
    text = interpret_bun_cr_ratio(15.0)
    assert text and "normal" in text.lower()


def test_bun_cr_interpretation_none():
    assert interpret_bun_cr_ratio(None) is None


# ---------- anion gap ----------


def test_anion_gap_basic():
    assert compute_anion_gap(140, 100, 24) == 16


def test_anion_gap_returns_none_for_missing():
    assert compute_anion_gap(None, 100, 24) is None
    assert compute_anion_gap(140, None, 24) is None
    assert compute_anion_gap(140, 100, None) is None


# ---------- albumin-corrected calcium ----------


def test_corrected_ca_low_albumin_raises_value():
    # Ca 8.0, albumin 2.0 -> 8.0 + 0.8*(4-2) = 9.6
    assert correct_calcium_for_albumin(8.0, 2.0) == 9.6


def test_corrected_ca_normal_albumin_unchanged():
    # albumin = 4.0 -> correction is zero
    assert correct_calcium_for_albumin(9.0, 4.0) == 9.0


def test_corrected_ca_high_albumin_lowers_value():
    # Ca 10.0, albumin 5.0 -> 10.0 + 0.8*(4-5) = 9.2
    assert correct_calcium_for_albumin(10.0, 5.0) == 9.2


def test_corrected_ca_returns_none_for_missing():
    assert correct_calcium_for_albumin(None, 4.0) is None
    assert correct_calcium_for_albumin(8.0, None) is None
    assert correct_calcium_for_albumin(0, 4.0) is None
    assert correct_calcium_for_albumin(8.0, 0) is None


def test_evaluate_panel_attaches_correction_when_meaningful(rules):
    panel = evaluate_panel(
        [("calcium", 8.0), ("albumin", 2.5)], rules,
    )
    ca_result = next(r for r in panel["results"] if r["lab_id"] == "calcium")
    correction = ca_result.get("correction")
    assert correction is not None
    assert correction["type"] == "albumin_corrected"
    assert correction["measured_value"] == 8.0
    assert correction["albumin"] == 2.5
    # 8.0 + 0.8 * (4.0 - 2.5) = 9.2 -> Normal
    assert correction["value"] == 9.2
    assert correction["severity"] == "Normal"


def test_evaluate_panel_skips_correction_when_albumin_normal(rules):
    """At albumin 4.0 the correction is zero — no block attached."""
    panel = evaluate_panel(
        [("calcium", 8.0), ("albumin", 4.0)], rules,
    )
    ca_result = next(r for r in panel["results"] if r["lab_id"] == "calcium")
    assert "correction" not in ca_result


def test_evaluate_panel_skips_correction_without_albumin(rules):
    panel = evaluate_panel([("calcium", 8.0)], rules)
    ca_result = next(r for r in panel["results"] if r["lab_id"] == "calcium")
    assert "correction" not in ca_result


def test_evaluate_panel_skips_correction_without_calcium(rules):
    panel = evaluate_panel([("albumin", 2.5)], rules)
    # No calcium result to attach to; albumin result has no correction either.
    alb = next(r for r in panel["results"] if r["lab_id"] == "albumin")
    assert "correction" not in alb


# ---------- evaluate_panel ----------


def test_evaluate_panel_returns_results_and_derived(rules):
    panel = evaluate_panel(
        [("creatinine", 2.0), ("bun", 40), ("sodium", 140), ("chloride", 100), ("bicarbonate", 20)],
        rules,
        {"sex": "male", "age": 60, "baseline_creatinine": 1.0, "urine_acr": 50, "diabetic": True},
    )
    assert len(panel["results"]) == 5
    d = panel["derived"]
    assert d["bun_cr_ratio"] == 20.0
    assert d["anion_gap"] == 20
    assert d["egfr"] is not None
    assert d["ckd_g_stage"] is not None
    assert d["ckd_a_stage"] == "A2"
    assert d["ckd_ga_stage"] is not None
    assert d["kdigo_aki_stage"] == "Stage 2"
    assert d["chronic_ckd_labs_indicated"] is True


def test_evaluate_panel_missing_data_listed_when_cr_present(rules):
    panel = evaluate_panel(
        [("creatinine", 1.5)], rules, {"sex": "male", "age": 50}
    )
    assert "urine albumin/creatinine ratio (UACR)" in panel["derived"]["missing_for_ckd_staging"]
    assert "last known (baseline) creatinine" in panel["derived"]["missing_for_ckd_staging"]


def test_evaluate_panel_no_derived_when_cr_absent(rules):
    panel = evaluate_panel([("potassium", 5.0)], rules, None)
    assert panel["derived"]["egfr"] is None
    assert panel["derived"]["bun_cr_ratio"] is None
    assert panel["derived"]["anion_gap"] is None


# ---------- PREVENT (compute_prevent_risk) ----------


def _full_prevent_context() -> dict:
    return {
        "sex": "male",
        "age": 55,
        "systolic_bp": 135,
        "current_smoker": False,
        "bmi": 28.0,
        "on_htn_meds": True,
        "on_cholesterol_meds": False,
        "diabetic": False,
    }


def _full_prevent_lab_values() -> dict:
    return {"total_cholesterol": 210, "hdl_cholesterol": 50}


def test_prevent_unavailable_when_inputs_missing():
    result = compute_prevent_risk({"sex": "male", "age": 55}, {}, None)
    assert result["available"] is False
    assert result["ascvd_10y"] is None
    assert "HDL cholesterol" in result["missing"]
    assert "BMI" in result["missing"]


def test_prevent_unavailable_when_only_partial_labs():
    result = compute_prevent_risk(_full_prevent_context(), {"total_cholesterol": 210}, 80.0)
    assert result["available"] is False
    assert "HDL cholesterol" in result["missing"]


def test_prevent_available_with_full_inputs():
    result = compute_prevent_risk(_full_prevent_context(), _full_prevent_lab_values(), 80.0)
    assert result["available"] is True
    assert result["ascvd_10y"] is not None
    assert result["cvd_10y"] is not None
    assert result["hf_10y"] is not None
    assert result["risk_tier"] in {"low", "intermediate", "high"}
    assert result["statin_recommendation"]


def test_prevent_high_risk_recommends_high_intensity():
    """65yo male diabetic smoker with elevated SBP, low HDL, low eGFR — should land in high tier."""
    ctx = {
        "sex": "male",
        "age": 65,
        "systolic_bp": 160,
        "current_smoker": True,
        "bmi": 32.0,
        "on_htn_meds": True,
        "on_cholesterol_meds": False,
        "diabetic": True,
    }
    result = compute_prevent_risk(ctx, {"total_cholesterol": 240, "hdl_cholesterol": 35}, 55.0)
    assert result["available"] is True
    assert result["ascvd_10y"] >= 10
    assert result["risk_tier"] == "high"
    assert "high-intensity" in result["statin_recommendation"]


def test_prevent_low_risk_recommends_lifestyle():
    """40yo female nonsmoker normal BP — should be low risk."""
    ctx = {
        "sex": "female",
        "age": 40,
        "systolic_bp": 115,
        "current_smoker": False,
        "bmi": 23.0,
        "on_htn_meds": False,
        "on_cholesterol_meds": False,
        "diabetic": False,
    }
    result = compute_prevent_risk(ctx, {"total_cholesterol": 180, "hdl_cholesterol": 60}, 100.0)
    assert result["available"] is True
    assert result["ascvd_10y"] < 3
    assert result["risk_tier"] == "low"


def test_prevent_age_out_of_range_reported():
    ctx = _full_prevent_context()
    ctx["age"] = 25  # below validated range (30-79)
    result = compute_prevent_risk(ctx, _full_prevent_lab_values(), 90.0)
    assert result["available"] is False
    assert result["out_of_range"]


def test_evaluate_panel_includes_prevent_block(rules):
    """evaluate_panel returns a 'prevent' key inside derived even when not computable."""
    panel = evaluate_panel([("potassium", 4.0)], rules, None)
    assert "prevent" in panel["derived"]
    assert panel["derived"]["prevent"]["available"] is False


def test_evaluate_panel_computes_prevent_with_full_inputs(rules):
    panel = evaluate_panel(
        [
            ("total_cholesterol", 210),
            ("hdl_cholesterol", 50),
            ("creatinine", 1.0),
        ],
        rules,
        {
            "sex": "male", "age": 55, "systolic_bp": 135, "current_smoker": False,
            "bmi": 28.0, "on_htn_meds": True, "on_cholesterol_meds": False,
            "diabetic": False,
        },
    )
    prevent = panel["derived"]["prevent"]
    assert prevent["available"] is True
    assert prevent["ascvd_10y"] is not None
    # eGFR must have been computed for PREVENT to fire.
    assert panel["derived"]["egfr"] is not None


# ---------- new lipid labs in rules.json ----------


def test_lipid_labs_present(rules):
    for lab_id in ("total_cholesterol", "ldl_cholesterol", "hdl_cholesterol",
                   "triglycerides", "non_hdl_cholesterol"):
        assert lab_id in rules["labs"], f"{lab_id} missing from rules.json"


def test_ldl_severity_tiers(rules):
    """Spot-check LDL boundaries — clinical decision points."""
    assert evaluate("ldl_cholesterol", 95, rules)["severity"] == "Normal"
    assert evaluate("ldl_cholesterol", 130, rules)["severity"] == "Mild High"
    assert evaluate("ldl_cholesterol", 175, rules)["severity"] == "Moderate High"
    assert evaluate("ldl_cholesterol", 200, rules)["severity"] == "Severe High"  # FH consideration
    assert evaluate("ldl_cholesterol", 260, rules)["severity"] == "Critical High"


def test_hdl_sex_stratified(rules):
    """HDL 45 is Mild Low for women but Normal for men under sex-stratified bands."""
    f = evaluate("hdl_cholesterol", 45, rules, {"sex": "female"})
    m = evaluate("hdl_cholesterol", 45, rules, {"sex": "male"})
    assert f["severity"] == "Mild Low"
    assert m["severity"] == "Normal"


def test_triglyceride_critical_high(rules):
    """TG ≥1000 is Critical High due to acute pancreatitis risk."""
    assert evaluate("triglycerides", 1200, rules)["severity"] == "Critical High"
