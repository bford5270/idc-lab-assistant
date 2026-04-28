"""Tests for the trend-aware evaluator (Phase 4 infrastructure).

Covers compute_trend_metrics() math, the priors-normalization helper,
evaluate() backward compat, and the trend-block shape attached to
evaluate's result. Lab-specific interpretation tests land in the
follow-up commits where each interpreter is added.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import (
    PriorValue,
    compute_trend_metrics,
    evaluate,
    evaluate_panel,
    load_rules,
    _normalize_priors,
    _parse_iso_date,
)


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


# ---------- _parse_iso_date ----------


def test_parse_iso_date_happy():
    assert _parse_iso_date("2026-01-15") == date(2026, 1, 15)
    assert _parse_iso_date(" 2026-01-15 ") == date(2026, 1, 15)


def test_parse_iso_date_returns_none_for_garbage():
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("") is None
    assert _parse_iso_date("   ") is None
    assert _parse_iso_date("6 months ago") is None
    assert _parse_iso_date("01/15/2026") is None  # not ISO
    assert _parse_iso_date(42) is None  # type: ignore[arg-type]


# ---------- _normalize_priors ----------


def test_normalize_priors_accepts_namedtuple():
    out = _normalize_priors([PriorValue(5.2, "2026-01-01")])
    assert out == [(5.2, date(2026, 1, 1))]


def test_normalize_priors_accepts_dict():
    out = _normalize_priors([{"value": 7.0, "date_str": "2026-02-15"}])
    assert out == [(7.0, date(2026, 2, 15))]


def test_normalize_priors_accepts_tuple():
    out = _normalize_priors([(7.0, "2026-02-15")])
    assert out == [(7.0, date(2026, 2, 15))]


def test_normalize_priors_drops_unparseable():
    out = _normalize_priors([
        (5.0, "not-a-date"),
        ("not-a-number", "2026-01-01"),
        (6.0, "2026-03-01"),
    ])
    assert out == [(6.0, date(2026, 3, 1))]


def test_normalize_priors_sorts_newest_first():
    out = _normalize_priors([
        (5.0, "2025-01-01"),
        (7.0, "2026-03-01"),
        (6.0, "2025-09-01"),
    ])
    assert [v for v, _ in out] == [7.0, 6.0, 5.0]


def test_normalize_priors_empty_input():
    assert _normalize_priors(None) == []
    assert _normalize_priors([]) == []


# ---------- compute_trend_metrics ----------


def test_trend_no_priors_returns_unavailable():
    m = compute_trend_metrics(5.0, [])
    assert m["available"] is False
    assert m["velocity_per_year"] is None
    assert m["delta"] is None


def test_trend_no_current_value_returns_unavailable():
    m = compute_trend_metrics(None, [(5.0, "2026-01-01")])
    assert m["available"] is False


def test_trend_basic_rising_psa():
    """PSA 4.0 today vs 3.0 a year ago -> velocity ~1.0 ng/mL/year, rising."""
    today = date(2026, 4, 28)
    one_year_ago = "2025-04-28"
    m = compute_trend_metrics(4.0, [(3.0, one_year_ago)], today=today)
    assert m["available"] is True
    assert m["n_priors"] == 1
    assert m["delta"] == 1.0
    assert abs(m["velocity_per_year"] - 1.0) < 0.01
    assert m["direction"] == "rising"
    assert m["baseline_value"] == 3.0
    assert m["baseline_date"] == "2025-04-28"
    assert m["span_days"] == 365


def test_trend_falling():
    today = date(2026, 4, 28)
    m = compute_trend_metrics(8.0, [(10.0, "2025-04-28")], today=today)
    assert m["delta"] == -2.0
    assert m["direction"] == "falling"
    assert m["velocity_per_year"] < 0


def test_trend_stable_within_5pct():
    """Within 5% of baseline -> stable, regardless of small numeric delta."""
    today = date(2026, 4, 28)
    m = compute_trend_metrics(10.2, [(10.0, "2025-10-28")], today=today)
    # delta_pct = +2% -> stable
    assert m["direction"] == "stable"


def test_trend_uses_most_recent_prior_as_baseline():
    """When multiple priors are supplied, baseline is the newest one."""
    today = date(2026, 4, 28)
    priors = [
        (5.0, "2025-01-01"),
        (6.0, "2025-09-01"),  # newest
        (4.5, "2024-06-01"),
    ]
    m = compute_trend_metrics(7.0, priors, today=today)
    assert m["baseline_value"] == 6.0
    assert m["baseline_date"] == "2025-09-01"
    assert m["n_priors"] == 3


def test_trend_handles_zero_baseline():
    """delta_pct should be None (not divide-by-zero) when baseline is 0."""
    today = date(2026, 4, 28)
    m = compute_trend_metrics(1.0, [(0.0, "2025-04-28")], today=today)
    assert m["delta"] == 1.0
    assert m["delta_pct"] is None
    # Direction defaults to stable when delta_pct is undefined
    assert m["direction"] == "stable"


def test_trend_drops_invalid_priors_silently():
    """Bad date / bad value entries are dropped; valid ones are used."""
    today = date(2026, 4, 28)
    priors = [
        (5.0, "garbage-date"),
        ("not-a-number", "2025-01-01"),
        (6.0, "2025-04-28"),
    ]
    m = compute_trend_metrics(7.0, priors, today=today)
    assert m["n_priors"] == 1
    assert m["baseline_value"] == 6.0


# ---------- evaluate() with priors ----------


def test_evaluate_without_priors_attaches_unavailable_trend(rules):
    """Backward compat: existing callers don't pass priors. Trend block
    is still attached (stable shape) but available=False."""
    res = evaluate("potassium", 4.0, rules, {})
    assert "trend" in res
    assert res["trend"]["available"] is False


def test_evaluate_with_priors_attaches_trend_block(rules):
    today = date(2026, 4, 28)
    priors = [PriorValue(3.5, "2025-04-28")]
    res = evaluate("potassium", 5.5, rules, {}, priors=priors)
    assert res["trend"]["available"] is True
    assert res["trend"]["delta"] == 2.0
    assert res["trend"]["direction"] == "rising"


def test_evaluate_panel_routes_priors_per_lab(rules):
    today = date(2026, 4, 28)
    priors_by_lab = {
        "potassium": [(3.5, "2025-04-28")],
        # creatinine has no priors; should still evaluate normally
    }
    panel = evaluate_panel(
        [("potassium", 5.5), ("creatinine", 1.2)],
        rules, {"sex": "male", "age": 50},
        priors_by_lab=priors_by_lab,
    )
    by_lab = {r["lab_id"]: r for r in panel["results"]}
    assert by_lab["potassium"]["trend"]["available"] is True
    assert by_lab["creatinine"]["trend"]["available"] is False


def test_evaluate_panel_no_priors_kwarg_is_backward_compatible(rules):
    """Calling evaluate_panel without priors_by_lab should still work."""
    panel = evaluate_panel([("potassium", 4.0)], rules)
    assert panel["results"][0]["trend"]["available"] is False


# ---------- PSA trend interpretation ----------


def test_psa_velocity_above_threshold_prompts_referral(rules):
    """PSA 4.5 today vs 3.0 a year ago -> velocity 1.5 ng/mL/year (>0.75)."""
    today = date(2026, 4, 28)
    res = evaluate(
        "psa", 4.5, rules, {"age": 60},
        priors=[(3.0, "2025-04-28")],
    )
    # Re-do with explicit today so the test is deterministic
    from engine import compute_trend_metrics, interpret_trend
    m = compute_trend_metrics(4.5, [(3.0, "2025-04-28")], today=today)
    text = interpret_trend("psa", 4.5, m, rules["labs"]["psa"])
    assert text is not None
    assert "0.75" in text
    assert "urology" in text.lower()


def test_psa_velocity_below_threshold_continues_surveillance(rules):
    """PSA 3.5 today vs 3.0 a year ago -> velocity 0.5/year (<0.75) — slow rise."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(3.5, [(3.0, "2025-04-28")], today=today)
    text = interpret_trend("psa", 3.5, m, rules["labs"]["psa"])
    assert text is not None
    assert "surveillance" in text.lower() or "below 0.75" in text.lower()


def test_psa_velocity_negative_treatment_response(rules):
    """PSA dropped >0.5 ng/mL in a year -> treatment response language."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(2.0, [(3.0, "2025-04-28")], today=today)
    text = interpret_trend("psa", 2.0, m, rules["labs"]["psa"])
    assert text is not None
    assert "declining" in text.lower() or "treatment response" in text.lower()


# ---------- Cr trend interpretation ----------


def test_cr_kdigo_aki_stage_1_when_within_window(rules):
    """Prior Cr 1.0 yesterday, current 1.4 -> Δ 0.4 mg/dL within 48h -> Stage 1."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(1.4, [(1.0, "2026-04-27")], today=today)
    text = interpret_trend("creatinine", 1.4, m, rules["labs"]["creatinine"])
    assert text is not None
    assert "Stage 1 AKI" in text


def test_cr_kdigo_aki_stage_3_at_3x_baseline(rules):
    """Prior 1.0 a week ago, current 3.5 -> ratio 3.5 -> Stage 3."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(3.5, [(1.0, "2026-04-22")], today=today)
    text = interpret_trend("creatinine", 3.5, m, rules["labs"]["creatinine"])
    assert text is not None
    assert "Stage 3 AKI" in text


def test_cr_chronic_uptrend_outside_kdigo_window(rules):
    """Prior 1.0 a year ago, current 1.5 -> outside KDIGO window — describe
    chronic upward trajectory, not AKI staging."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(1.5, [(1.0, "2025-04-28")], today=today)
    text = interpret_trend("creatinine", 1.5, m, rules["labs"]["creatinine"])
    assert text is not None
    assert "Stage" not in text  # not AKI staging
    assert "Re-assess" in text or "trending up" in text.lower()


# ---------- A1C trend interpretation ----------


def test_a1c_improving(rules):
    """A1C 8.5 -> 7.5 over a year -> improving by 1.0%."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(7.5, [(8.5, "2025-04-28")], today=today)
    text = interpret_trend("hba1c", 7.5, m, rules["labs"]["hba1c"])
    assert text is not None
    assert "improving" in text.lower()


def test_a1c_worsening(rules):
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(8.5, [(7.5, "2025-04-28")], today=today)
    text = interpret_trend("hba1c", 8.5, m, rules["labs"]["hba1c"])
    assert text is not None
    assert "worsening" in text.lower()
    assert "intensification" in text.lower() or "ada" in text.lower()


def test_a1c_stable(rules):
    """Within 0.5% delta -> stable."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(7.3, [(7.5, "2025-04-28")], today=today)
    text = interpret_trend("hba1c", 7.3, m, rules["labs"]["hba1c"])
    assert text is not None
    assert "stable" in text.lower()


# ---------- Lab without registered interpreter ----------


def test_unregistered_lab_returns_none(rules):
    """Sodium has no trend interpreter -> returns None even with priors."""
    from engine import compute_trend_metrics, interpret_trend
    today = date(2026, 4, 28)
    m = compute_trend_metrics(140, [(135, "2025-04-28")], today=today)
    text = interpret_trend("sodium", 140, m, rules["labs"]["sodium"])
    assert text is None


# ---------- K trend ----------


def _interp(rules, lab_id, current, prior_value, prior_date_str, today=None):
    from engine import compute_trend_metrics, interpret_trend
    today = today or date(2026, 4, 28)
    m = compute_trend_metrics(current, [(prior_value, prior_date_str)], today=today)
    return interpret_trend(lab_id, current, m, rules["labs"][lab_id])


def test_k_acute_uptrend_review_meds(rules):
    text = _interp(rules, "potassium", 5.6, 4.5, "2026-04-21")  # 7d
    assert text is not None
    assert "trending up acutely" in text.lower()
    assert "acei" in text.lower() or "spironolactone" in text.lower()


def test_k_acute_downtrend_check_mg(rules):
    text = _interp(rules, "potassium", 3.2, 4.0, "2026-04-21")  # 7d
    assert text is not None
    assert "trending down acutely" in text.lower()
    assert "mg" in text.lower()


def test_k_chronic_uptrend(rules):
    text = _interp(rules, "potassium", 5.4, 4.3, "2025-04-28")
    assert text is not None
    assert "chronic uptrend" in text.lower()
    assert "ckd" in text.lower() or "raas" in text.lower()


# ---------- Hgb trend ----------


def test_hgb_acute_drop_bleeding_workup(rules):
    """1.5 g/dL drop in 7 days -> acute drop language."""
    text = _interp(rules, "hemoglobin", 11.0, 12.5, "2026-04-21")
    assert text is not None
    assert "dropped" in text.lower()
    assert "bleeding" in text.lower()


def test_hgb_chronic_decline(rules):
    text = _interp(rules, "hemoglobin", 11.0, 13.0, "2025-04-28")
    assert text is not None
    assert "chronic decline" in text.lower()
    assert "iron" in text.lower() or "mcv" in text.lower()


def test_hgb_chronic_improvement(rules):
    text = _interp(rules, "hemoglobin", 13.5, 11.0, "2025-04-28")
    assert text is not None
    assert "improvement" in text.lower()


# ---------- ALT trend ----------


def test_alt_resolving_after_acute(rules):
    """ALT 200 → 60 over 6 months — >50% drop, resolving."""
    text = _interp(rules, "alt", 60, 200, "2025-10-28")
    assert text is not None
    assert "improving" in text.lower() or "resolving" in text.lower()


def test_alt_persistent_elevation(rules):
    """ALT 80 → 75 over 1 year — persistent elevation, not improving."""
    text = _interp(rules, "alt", 75, 80, "2025-04-28")
    assert text is not None
    assert "persistently" in text.lower() or "fib-4" in text.lower()


# ---------- LDL trend ----------


def test_ldl_high_intensity_response(rules):
    """LDL 160 → 70 = 56% drop -> high-intensity statin response language."""
    text = _interp(rules, "ldl_cholesterol", 70, 160, "2025-04-28")
    assert text is not None
    assert "≥50%" in text or "high-intensity" in text.lower()


def test_ldl_moderate_intensity_response(rules):
    """LDL 130 → 90 = 31% drop -> moderate-intensity statin response."""
    text = _interp(rules, "ldl_cholesterol", 90, 130, "2025-04-28")
    assert text is not None
    assert "30" in text and "49" in text


def test_ldl_worsening(rules):
    """LDL 90 → 130 = 44% rise -> worsening."""
    text = _interp(rules, "ldl_cholesterol", 130, 90, "2025-04-28")
    assert text is not None
    assert "worsening" in text.lower()
    assert "adherence" in text.lower()


# ---------- TSH trend ----------


def test_tsh_normalized_on_levothyroxine(rules):
    """TSH 8.0 → 2.5 — normalization on therapy."""
    text = _interp(rules, "tsh", 2.5, 8.0, "2025-10-28")
    assert text is not None
    assert "normalized" in text.lower()
    assert "levothyroxine" in text.lower()


def test_tsh_worsening_on_therapy(rules):
    """Already-elevated TSH rising further — adherence / absorption review."""
    text = _interp(rules, "tsh", 12.0, 8.0, "2025-10-28")
    assert text is not None
    assert "adherence" in text.lower() or "absorption" in text.lower()


def test_tsh_recovering_from_suppression(rules):
    """Suppressed TSH rising back above 0.4 — antithyroid response."""
    text = _interp(rules, "tsh", 0.5, 0.05, "2025-10-28")
    assert text is not None
    assert "recovering" in text.lower()
