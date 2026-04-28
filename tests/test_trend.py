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
