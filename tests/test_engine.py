"""Tests for engine.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import (
    ELDERLY_AGE_THRESHOLD,
    URGENCY_BY_SEVERITY,
    assign_ckd_a_stage,
    assign_ckd_g_stage,
    chronic_ckd_labs_indicated,
    classify_anemia_by_mcv,
    classify_lft_pattern,
    compute_anion_gap,
    compute_bun_cr_ratio,
    compute_egfr,
    compute_kdigo_aki_stage,
    compute_lft_r_factor,
    compute_prevent_risk,
    correct_calcium_for_albumin,
    elderly_thresholds_in_use,
    evaluate,
    evaluate_panel,
    find_severity,
    interpret_anemia_workup,
    interpret_bun_cr_ratio,
    interpret_lft_pattern,
    load_rules,
    pick_follow_up_dict,
    pick_thresholds,
    pregnancy_thresholds_in_use,
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
        if lab_def.get("kind") == "serology":
            assert "inputs" in lab_def, f"{lab_id} (serology) missing inputs"
            assert "patterns" in lab_def, f"{lab_id} (serology) missing patterns"
            continue
        assert "synonyms" in lab_def, f"{lab_id} missing synonyms"
        assert "unit" in lab_def, f"{lab_id} missing unit"
        assert "thresholds" in lab_def or "thresholds_by_context" in lab_def, \
            f"{lab_id} missing thresholds"


def test_every_threshold_has_severity(rules):
    for lab_id, lab_def in rules["labs"].items():
        if lab_def.get("kind") == "serology":
            continue
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


# ---------- pregnancy thresholds ----------


def test_pick_thresholds_uses_pregnancy_band_when_pregnant(rules):
    """TSH 3.0 is Normal non-pregnant but Mild High in pregnancy."""
    tsh = rules["labs"]["tsh"]
    thresholds, used_default = pick_thresholds(tsh, {"pregnancy": True})
    assert used_default is False
    # Pregnancy band: 0.3-2.5 normal, 2.5-4.0 Mild High
    assert find_severity(3.0, thresholds) == "Mild High"


def test_pick_thresholds_default_band_when_not_pregnant(rules):
    """Same TSH 3.0 should be Normal in the default band."""
    tsh = rules["labs"]["tsh"]
    thresholds, _ = pick_thresholds(tsh, {})
    assert find_severity(3.0, thresholds) == "Normal"


def test_pick_thresholds_pregnancy_takes_precedence_over_sex(rules):
    """If a lab had both pregnancy and sex bands, pregnancy wins."""
    fake = {
        "thresholds_by_context": {
            "default": [{"severity": "Normal"}],
            "female": [{"severity": "Female-band"}],
            "pregnancy": [{"severity": "Pregnancy-band"}],
        }
    }
    thresholds, _ = pick_thresholds(
        fake, {"sex": "female", "pregnancy": True}
    )
    assert thresholds[0]["severity"] == "Pregnancy-band"


def test_pregnancy_thresholds_in_use_flag(rules):
    tsh = rules["labs"]["tsh"]
    assert pregnancy_thresholds_in_use(tsh, {"pregnancy": True}) is True
    assert pregnancy_thresholds_in_use(tsh, {"pregnancy": False}) is False
    assert pregnancy_thresholds_in_use(tsh, None) is False
    # Lab without pregnancy band → False even if pregnant
    potassium = rules["labs"]["potassium"]
    assert pregnancy_thresholds_in_use(potassium, {"pregnancy": True}) is False


def test_evaluate_tsh_pregnancy_severity_shift(rules):
    """End-to-end: same value, severity flips when pregnancy=True."""
    non_preg = evaluate("tsh", 3.0, rules, {})
    preg = evaluate("tsh", 3.0, rules, {"pregnancy": True})
    assert non_preg["severity"] == "Normal"
    assert preg["severity"] == "Mild High"
    assert preg["pregnancy_thresholds"] is True
    assert non_preg["pregnancy_thresholds"] is False


def test_evaluate_tsh_pregnancy_normal_lower_bound(rules):
    """TSH 0.35 is Normal in default but Mild Low in pregnancy (< 0.3 floor of 0.3)."""
    # Non-pregnant default Normal band: 0.4-4.0; 0.35 is Mild Low (0.1-0.4)
    non_preg = evaluate("tsh", 0.35, rules, {})
    assert non_preg["severity"] == "Mild Low"
    # Pregnancy Normal band: 0.3-2.5; 0.35 is Normal
    preg = evaluate("tsh", 0.35, rules, {"pregnancy": True})
    assert preg["severity"] == "Normal"


# ---------- trimester-specific TSH ----------


def test_tsh_trimester_T1_uses_more_conservative_upper(rules):
    """T1 upper Normal is 2.5; T2 is 3.0. Same TSH=2.7 should split severity."""
    t1 = evaluate("tsh", 2.7, rules, {"pregnancy": True, "trimester": 1})
    t2 = evaluate("tsh", 2.7, rules, {"pregnancy": True, "trimester": 2})
    assert t1["severity"] == "Mild High"
    assert t2["severity"] == "Normal"
    assert t1["pregnancy_thresholds"] is True
    assert t2["pregnancy_thresholds"] is True


def test_tsh_trimester_falls_back_to_generic_when_unknown(rules):
    """Unknown trimester -> generic pregnancy band (Normal upper 2.5)."""
    res = evaluate("tsh", 2.7, rules, {"pregnancy": True})
    assert res["severity"] == "Mild High"


def test_tsh_invalid_trimester_falls_back(rules):
    """Trimester outside 1-3 is ignored; generic pregnancy band used."""
    res = evaluate("tsh", 2.7, rules, {"pregnancy": True, "trimester": 4})
    assert res["severity"] == "Mild High"


def test_pick_thresholds_trimester_outranks_generic_pregnancy(rules):
    """When both pregnancy and pregnancy_TN exist, the trimester-specific
    band is selected."""
    tsh = rules["labs"]["tsh"]
    thresh, _ = pick_thresholds(
        tsh, {"pregnancy": True, "trimester": 3}
    )
    # T3 Normal is 0.4-3.0; should match T3 band
    assert find_severity(0.35, thresh) == "Mild Low"  # T3 Mild Low 0.1-0.4
    assert find_severity(2.7, thresh) == "Normal"     # T3 Normal 0.4-3.0


# ---------- elderly TSH + age-conditioning ----------


def test_tsh_elderly_widens_upper_normal(rules):
    """Age 75 + TSH 4.5 should be Normal (elderly band 0.4-5.0); same value
    is Mild High in default band."""
    elderly = evaluate("tsh", 4.5, rules, {"age": 75})
    young = evaluate("tsh", 4.5, rules, {"age": 50})
    assert elderly["severity"] == "Normal"
    assert young["severity"] == "Mild High"
    assert elderly["elderly_thresholds"] is True
    assert young["elderly_thresholds"] is False


def test_elderly_thresholds_in_use_at_boundary(rules):
    tsh = rules["labs"]["tsh"]
    assert elderly_thresholds_in_use(tsh, {"age": ELDERLY_AGE_THRESHOLD}) is True
    assert elderly_thresholds_in_use(tsh, {"age": ELDERLY_AGE_THRESHOLD - 1}) is False


def test_pregnancy_outranks_elderly(rules):
    """75yo pregnant patient (rare but possible — gestational carrier, etc.)
    should get pregnancy bands, not elderly. Pregnancy dominates."""
    res = evaluate("tsh", 4.5, rules, {"pregnancy": True, "age": 75})
    # Pregnancy Normal upper is 2.5 -> 4.5 is Moderate High (4.0-10.0)
    # Elderly Normal upper is 5.0 -> 4.5 would be Normal there
    assert res["pregnancy_thresholds"] is True
    assert res["elderly_thresholds"] is False
    assert res["severity"] == "Moderate High"


def test_elderly_only_applies_when_band_present(rules):
    """Sodium has no 'elderly' band -> age 75 falls through to default/sex."""
    # Sodium has only static `thresholds`, so context doesn't change anything
    res = evaluate("sodium", 138, rules, {"age": 80})
    assert res["elderly_thresholds"] is False


# ---------- pregnancy bands for Hgb / ALP / Cr ----------


def test_hgb_pregnancy_normal_floor_is_11(rules):
    """Hgb 11.5 is Mild Low for non-pregnant female (Normal floor 12.0) but
    Normal in pregnancy (Normal floor 11.0)."""
    non_preg = evaluate("hemoglobin", 11.5, rules, {"sex": "female"})
    preg = evaluate(
        "hemoglobin", 11.5, rules, {"sex": "female", "pregnancy": True}
    )
    assert non_preg["severity"] == "Mild Low"
    assert preg["severity"] == "Normal"


def test_alp_pregnancy_doesnt_overflag_t3_level(rules):
    """ALP 200 is Mild High non-pregnant (>130) but Normal in pregnancy
    (placental ALP raises baseline 2-3x; pregnancy Normal extends to 260)."""
    non_preg = evaluate("alkaline_phosphatase", 200, rules, {})
    preg = evaluate("alkaline_phosphatase", 200, rules, {"pregnancy": True})
    assert non_preg["severity"] == "Mild High"
    assert preg["severity"] == "Normal"


def test_creatinine_pregnancy_lower_normal_ceiling(rules):
    """Cr 1.0 is Normal for non-pregnant female (Normal 0.5-1.1) but
    Mild High in pregnancy (Normal 0.4-0.9; pregnancy GFR rises ~50%)."""
    non_preg = evaluate("creatinine", 1.0, rules, {"sex": "female"})
    preg = evaluate(
        "creatinine", 1.0, rules, {"sex": "female", "pregnancy": True}
    )
    assert non_preg["severity"] == "Normal"
    assert preg["severity"] == "Mild High"


def test_creatinine_pregnancy_outranks_sex(rules):
    """Pregnant patient with sex=female should get pregnancy band, not female."""
    cr_def = rules["labs"]["creatinine"]
    thresh, _ = pick_thresholds(
        cr_def, {"sex": "female", "pregnancy": True}
    )
    # Pregnancy Normal max is 0.9; female Normal max is 1.1
    assert find_severity(1.0, thresh) == "Mild High"


# ---------- PSA age-specific bands ----------


def test_psa_age_45_uses_age_40_49_band(rules):
    """PSA 3.0 is Mild High at age 45 (40–49 band Normal <2.5) but Normal
    in default band (<4.0)."""
    young = evaluate("psa", 3.0, rules, {"age": 45})
    no_age = evaluate("psa", 3.0, rules, {})
    assert young["severity"] == "Mild High"
    assert no_age["severity"] == "Normal"


def test_psa_age_55_uses_age_50_59_band(rules):
    """PSA 3.8 is Mild High at age 55 (50–59 band Normal <3.5)."""
    res = evaluate("psa", 3.8, rules, {"age": 55})
    assert res["severity"] == "Mild High"


def test_psa_age_65_uses_age_60_69_band(rules):
    """PSA 5.0 is Mild High at age 65 (60–69 band Normal <4.5) but Mild
    High in default (4.0–10) too — both flag, different reasoning."""
    res = evaluate("psa", 5.0, rules, {"age": 65})
    assert res["severity"] == "Mild High"


def test_psa_age_75_uses_age_70_plus_band(rules):
    """PSA 5.5 is Normal at age 75 (70+ band Normal <6.5) but Mild High
    in default (>4.0). The age-bracket band catches age-related rise."""
    res = evaluate("psa", 5.5, rules, {"age": 75})
    assert res["severity"] == "Normal"


def test_psa_age_below_40_uses_default(rules):
    """No age bracket below 40; falls through to default."""
    res = evaluate("psa", 4.5, rules, {"age": 30})
    # Default Normal <4.0; 4.5 is Mild High (4.0-10)
    assert res["severity"] == "Mild High"
    # threshold_used_default is True since no bracket key matched
    assert res["threshold_used_default"] is True


def test_psa_no_age_uses_default(rules):
    res = evaluate("psa", 5.0, rules, {})
    assert res["severity"] == "Mild High"
    assert res["threshold_used_default"] is True


def test_psa_pregnancy_does_not_apply(rules):
    """PSA has no pregnancy band, but age bracket should still work
    when pregnancy is set (PSA wouldn't be ordered in pregnant patient
    but the engine shouldn't crash)."""
    res = evaluate("psa", 5.0, rules, {"age": 65, "pregnancy": True})
    # No pregnancy band on PSA, so falls to age_60_69
    assert res["severity"] == "Mild High"


def test_age_bracket_helper():
    """_age_bracket_key boundary cases."""
    from engine import _age_bracket_key
    assert _age_bracket_key(None) is None
    assert _age_bracket_key(39) is None
    assert _age_bracket_key(40) == "age_40_49"
    assert _age_bracket_key(49) == "age_40_49"
    assert _age_bracket_key(50) == "age_50_59"
    assert _age_bracket_key(59) == "age_50_59"
    assert _age_bracket_key(60) == "age_60_69"
    assert _age_bracket_key(69) == "age_60_69"
    assert _age_bracket_key(70) == "age_70_plus"
    assert _age_bracket_key(95) == "age_70_plus"


# ---------- TB PPD risk-stratified bands ----------


def test_ppd_high_risk_5mm_positive(rules):
    """Induration 6 mm in HIV+ / recent contact / immunosuppressed -> Mild High."""
    res = evaluate("tb_ppd", 6, rules, {"tb_risk_category": "high"})
    assert res["severity"] == "Mild High"


def test_ppd_high_risk_4mm_negative(rules):
    res = evaluate("tb_ppd", 4, rules, {"tb_risk_category": "high"})
    assert res["severity"] == "Normal"


def test_ppd_moderate_risk_10mm_positive(rules):
    res = evaluate("tb_ppd", 10, rules, {"tb_risk_category": "moderate"})
    assert res["severity"] == "Mild High"


def test_ppd_moderate_risk_8mm_negative(rules):
    res = evaluate("tb_ppd", 8, rules, {"tb_risk_category": "moderate"})
    assert res["severity"] == "Normal"


def test_ppd_low_risk_15mm_positive(rules):
    res = evaluate("tb_ppd", 15, rules, {"tb_risk_category": "low"})
    assert res["severity"] == "Mild High"


def test_ppd_low_risk_12mm_negative(rules):
    """12 mm is positive in moderate risk but negative in low risk —
    risk-stratified cutoffs do their job."""
    low = evaluate("tb_ppd", 12, rules, {"tb_risk_category": "low"})
    moderate = evaluate("tb_ppd", 12, rules, {"tb_risk_category": "moderate"})
    assert low["severity"] == "Normal"
    assert moderate["severity"] == "Mild High"


def test_ppd_strongly_positive_15mm_in_high_risk(rules):
    """≥15 mm gets Severe High in any risk category — active TB workup
    priority."""
    res = evaluate("tb_ppd", 18, rules, {"tb_risk_category": "high"})
    assert res["severity"] == "Severe High"


def test_ppd_no_risk_category_uses_default(rules):
    """No tb_risk_category -> default band (low-risk equivalent: Normal <15)."""
    res = evaluate("tb_ppd", 12, rules, {})
    assert res["severity"] == "Normal"
    assert res["threshold_used_default"] is True


def test_ppd_invalid_risk_category_falls_to_default(rules):
    """Unrecognized risk category string -> falls through to default."""
    res = evaluate("tb_ppd", 12, rules, {"tb_risk_category": "very_high"})
    assert res["severity"] == "Normal"
    assert res["threshold_used_default"] is True


def test_ppd_pregnancy_does_not_override_tb_risk(rules):
    """tb_ppd has no pregnancy band, so tb_risk_category should still
    drive cutoff even when pregnancy=True."""
    res = evaluate("tb_ppd", 6, rules, {
        "pregnancy": True, "tb_risk_category": "high",
    })
    assert res["severity"] == "Mild High"


# ---------- LFT pattern (R-factor) ----------


def test_lft_r_factor_hepatocellular_clearcut():
    """ALT 10x ULN, ALP normal -> R well above 5."""
    r = compute_lft_r_factor(alt=420, alp=100, sex="male")  # alt_uln=42, alp_uln=130
    # (420/42) / (100/130) = 10 / 0.769 ≈ 13
    assert r is not None and r > 5
    assert classify_lft_pattern(r) == "hepatocellular"


def test_lft_r_factor_cholestatic_clearcut():
    """ALP elevated, ALT near normal -> R below 2."""
    r = compute_lft_r_factor(alt=40, alp=400, sex="male")
    # (40/42) / (400/130) = 0.952 / 3.077 ≈ 0.31
    assert r is not None and r < 2
    assert classify_lft_pattern(r) == "cholestatic"


def test_lft_r_factor_mixed():
    """ALT and ALP both moderately elevated."""
    r = compute_lft_r_factor(alt=100, alp=260, sex="male")
    # (100/42) / (260/130) = 2.38 / 2.0 ≈ 1.19 -> cholestatic
    # Use values that produce 2-5
    r = compute_lft_r_factor(alt=200, alp=200, sex="male")
    # (200/42) / (200/130) = 4.76 / 1.54 ≈ 3.10 -> mixed
    assert r is not None
    assert classify_lft_pattern(r) == "mixed"


def test_lft_r_factor_uses_sex_specific_alt_uln():
    """Female ULN (33) gives a higher R-factor than male ULN (42) for same ALT."""
    r_male = compute_lft_r_factor(alt=100, alp=100, sex="male")
    r_female = compute_lft_r_factor(alt=100, alp=100, sex="female")
    assert r_female > r_male


def test_lft_r_factor_returns_none_when_both_normal():
    """No injury to classify when both labs are within ULN."""
    assert compute_lft_r_factor(alt=20, alp=80, sex="male") is None


def test_lft_r_factor_returns_none_for_missing_inputs():
    assert compute_lft_r_factor(None, 100, "male") is None
    assert compute_lft_r_factor(100, None, "male") is None
    assert compute_lft_r_factor(0, 100, "male") is None
    assert compute_lft_r_factor(100, 0, "male") is None


def test_classify_lft_pattern_returns_none_for_none():
    assert classify_lft_pattern(None) is None


def test_interpret_lft_pattern_includes_pattern_name():
    text = interpret_lft_pattern("hepatocellular", 13.0)
    assert text is not None
    assert "hepatocellular" in text.lower()
    assert "13" in text


def test_evaluate_panel_surfaces_lft_pattern(rules):
    panel = evaluate_panel(
        [("alt", 420), ("alkaline_phosphatase", 100), ("ast", 200)], rules,
        {"sex": "male"},
    )
    d = panel["derived"]
    assert d["lft_r_factor"] is not None
    assert d["lft_r_factor"] > 5
    assert d["lft_pattern"] == "hepatocellular"
    assert "hepatocellular" in d["lft_pattern_interpretation"].lower()


def test_evaluate_panel_no_lft_pattern_without_alp(rules):
    panel = evaluate_panel([("alt", 420)], rules, {"sex": "male"})
    d = panel["derived"]
    assert d["lft_r_factor"] is None
    assert d["lft_pattern"] is None
    assert d["lft_pattern_interpretation"] is None


def test_evaluate_panel_no_lft_pattern_when_both_normal(rules):
    panel = evaluate_panel(
        [("alt", 20), ("alkaline_phosphatase", 80)], rules, {"sex": "male"},
    )
    d = panel["derived"]
    assert d["lft_r_factor"] is None
    assert d["lft_pattern"] is None


# ---------- anemia workup (MCV-driven) ----------


def test_classify_anemia_by_mcv_microcytic():
    assert classify_anemia_by_mcv(70) == "microcytic"
    assert classify_anemia_by_mcv(79.9) == "microcytic"


def test_classify_anemia_by_mcv_normocytic():
    assert classify_anemia_by_mcv(80) == "normocytic"
    assert classify_anemia_by_mcv(90) == "normocytic"
    assert classify_anemia_by_mcv(100) == "normocytic"


def test_classify_anemia_by_mcv_macrocytic():
    assert classify_anemia_by_mcv(101) == "macrocytic"
    assert classify_anemia_by_mcv(120) == "macrocytic"


def test_classify_anemia_by_mcv_returns_none_for_missing():
    assert classify_anemia_by_mcv(None) is None
    assert classify_anemia_by_mcv(0) is None


def test_interpret_anemia_workup_includes_mcv_and_pattern_keywords():
    micro = interpret_anemia_workup("microcytic", 70)
    assert micro is not None and "70" in micro and "ferritin" in micro.lower()
    macro = interpret_anemia_workup("macrocytic", 115)
    assert macro is not None and "115" in macro and "b12" in macro.lower()
    normo = interpret_anemia_workup("normocytic", 90)
    assert normo is not None and "reticulocyte" in normo.lower()


def test_evaluate_panel_surfaces_anemia_pattern_when_anemic_and_mcv_present(rules):
    """Female Hgb 9 (Moderate Low) + MCV 72 -> microcytic anemia workup."""
    panel = evaluate_panel(
        [("hemoglobin", 9.0), ("mcv", 72)], rules,
        {"sex": "female"},
    )
    d = panel["derived"]
    assert d["anemia_pattern"] == "microcytic"
    assert "ferritin" in d["anemia_workup"].lower()


def test_evaluate_panel_no_anemia_pattern_when_hgb_normal(rules):
    """Hgb in Normal range -> don't surface anemia workup even if MCV is unusual."""
    panel = evaluate_panel(
        [("hemoglobin", 14.0), ("mcv", 110)], rules,
        {"sex": "female"},
    )
    d = panel["derived"]
    assert d["anemia_pattern"] is None
    assert d["anemia_workup"] is None


def test_evaluate_panel_no_anemia_pattern_without_mcv(rules):
    """Anemic Hgb but no MCV -> can't classify."""
    panel = evaluate_panel([("hemoglobin", 9.0)], rules, {"sex": "female"})
    d = panel["derived"]
    assert d["anemia_pattern"] is None


def test_evaluate_panel_anemia_pattern_macrocytic(rules):
    """Hgb low, MCV 115 -> macrocytic with B12/folate guidance."""
    panel = evaluate_panel(
        [("hemoglobin", 10.0), ("mcv", 115)], rules,
        {"sex": "male"},
    )
    d = panel["derived"]
    assert d["anemia_pattern"] == "macrocytic"
    assert "b12" in d["anemia_workup"].lower()


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
