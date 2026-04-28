"""Engine for evaluating lab values against rules.json.

Pure module — no Streamlit imports. Testable independently.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple


class PriorValue(NamedTuple):
    """A single prior lab observation. `date_str` is parsed leniently —
    'YYYY-MM-DD' is preferred; freeform strings ('6 months ago') are
    surfaced for documentation but excluded from numeric computations.
    """
    value: float
    date_str: str


def _parse_iso_date(s: str | None) -> date | None:
    """Parse an ISO-8601 date or return None on any failure. Whitespace
    is stripped; non-ISO strings (e.g. '6 months ago') return None and
    the caller can still display the raw string."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _normalize_priors(
    priors: list | None,
) -> list[tuple[float, date]]:
    """Coerce a heterogeneous prior list into [(value, date), ...] sorted
    newest-first. Accepts PriorValue tuples or (value, date_str) tuples
    or {'value': ..., 'date_str': ...} dicts. Drops any entry without
    both a parseable numeric value and a parseable ISO date."""
    if not priors:
        return []
    out: list[tuple[float, date]] = []
    for p in priors:
        if isinstance(p, PriorValue):
            v, d = p.value, p.date_str
        elif isinstance(p, dict):
            v = p.get("value")
            d = p.get("date_str") or p.get("date")
        elif isinstance(p, (tuple, list)) and len(p) >= 2:
            v, d = p[0], p[1]
        else:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        parsed = _parse_iso_date(d)
        if parsed is None:
            continue
        out.append((v, parsed))
    out.sort(key=lambda item: item[1], reverse=True)
    return out


def compute_trend_metrics(
    current_value: float | None,
    priors: list | None,
    today: date | None = None,
) -> dict:
    """Compute velocity (per year), delta (vs most recent prior),
    direction, and anchor metadata for a current value + prior list.

    Returns a stable shape so callers can rely on the keys whether or
    not priors were supplied:

        {
          "available": bool,         # True iff at least one usable prior
          "n_priors": int,
          "velocity_per_year": float | None,
          "delta": float | None,             # current - most-recent prior
          "delta_pct": float | None,         # % change vs most recent
          "direction": str | None,           # "rising" / "falling" / "stable"
          "baseline_value": float | None,    # most-recent prior's value
          "baseline_date": str | None,       # ISO date string
          "span_days": int | None,           # days between baseline and today
          "span_years": float | None,
        }

    `today` is overrideable for tests; defaults to date.today().
    """
    empty = {
        "available": False, "n_priors": 0,
        "velocity_per_year": None, "delta": None, "delta_pct": None,
        "direction": None, "baseline_value": None, "baseline_date": None,
        "span_days": None, "span_years": None,
    }
    if current_value is None:
        return empty

    normalized = _normalize_priors(priors)
    if not normalized:
        return empty

    baseline_value, baseline_date = normalized[0]
    anchor = today or date.today()
    span_days = (anchor - baseline_date).days
    span_years = span_days / 365.25 if span_days else 0.0

    delta = current_value - baseline_value
    delta_pct = (delta / baseline_value * 100) if baseline_value else None
    velocity = (delta / span_years) if span_years and span_years > 0 else None

    if delta_pct is None or abs(delta_pct) < 5.0:
        direction = "stable"
    elif delta_pct > 0:
        direction = "rising"
    else:
        direction = "falling"

    return {
        "available": True,
        "n_priors": len(normalized),
        "velocity_per_year": round(velocity, 3) if velocity is not None else None,
        "delta": round(delta, 3),
        "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        "direction": direction,
        "baseline_value": baseline_value,
        "baseline_date": baseline_date.isoformat(),
        "span_days": span_days,
        "span_years": round(span_years, 2),
    }


def load_rules(path: str | Path = "rules.json") -> dict:
    """Load the canonical rules JSON."""
    with open(path) as f:
        return json.load(f)


ELDERLY_AGE_THRESHOLD = 70


def _age_bracket_key(age: int | float | None) -> str | None:
    """Map a numeric age to an age-bracket lookup key (PSA uses these).

    Brackets follow the Oesterling-derived age-specific PSA reference
    ranges (40-49, 50-59, 60-69, 70+). Returns None if age is missing
    or below 40 — labs that opt into bracket bands fall back to default.
    """
    if age is None or age < 40:
        return None
    if age < 50:
        return "age_40_49"
    if age < 60:
        return "age_50_59"
    if age < 70:
        return "age_60_69"
    return "age_70_plus"


def pick_thresholds(lab_def: dict, context: dict | None) -> tuple[list[dict], bool]:
    """Pick the appropriate threshold list for the given patient context.

    Returns (thresholds_list, used_default_flag). used_default_flag is True
    when we fell back to the 'default' band set because the relevant context
    key (sex, pregnancy, age) was not provided or not recognized.

    Lookup order — first match wins:
    1. pregnancy_T<N> (trimester-specific, when context.trimester ∈ {1, 2, 3})
    2. pregnancy (generic pregnancy fallback)
    3. TB risk category (high_risk / moderate_risk / low_risk — used by
       tb_ppd per CDC induration cutoffs)
    4. age bracket (age_40_49 / age_50_59 / age_60_69 / age_70_plus —
       used by PSA per Oesterling-derived age-specific ranges)
    5. elderly (when context.age >= ELDERLY_AGE_THRESHOLD; broader than
       age_70_plus for labs that only differentiate elderly vs not)
    6. sex (female / male)
    7. default

    Pregnancy outranks age and sex because pregnancy-specific reference
    ranges (ATA 2017 TSH, ACOG Cr) differ fundamentally from age- or
    sex-adjusted bands.
    """
    if "thresholds" in lab_def:
        return lab_def["thresholds"], False

    by_context = lab_def.get("thresholds_by_context", {})
    ctx = context or {}

    if ctx.get("pregnancy") is True:
        trimester = ctx.get("trimester")
        if trimester in (1, 2, 3):
            tri_key = f"pregnancy_T{trimester}"
            if tri_key in by_context:
                return by_context[tri_key], False
        if "pregnancy" in by_context:
            return by_context["pregnancy"], False

    tb_risk = ctx.get("tb_risk_category")
    if tb_risk in ("high", "moderate", "low"):
        tb_key = f"{tb_risk}_risk"
        if tb_key in by_context:
            return by_context[tb_key], False

    age = ctx.get("age")
    bracket = _age_bracket_key(age)
    if bracket and bracket in by_context:
        return by_context[bracket], False

    if (
        age is not None
        and age >= ELDERLY_AGE_THRESHOLD
        and "elderly" in by_context
    ):
        return by_context["elderly"], False

    sex = ctx.get("sex")
    if sex and sex in by_context:
        return by_context[sex], False

    return by_context.get("default", []), True


def pregnancy_thresholds_in_use(lab_def: dict, context: dict | None) -> bool:
    """True iff pick_thresholds will pick a pregnancy-specific band set
    (trimester-specific or generic)."""
    if "thresholds" in lab_def:
        return False
    by_context = lab_def.get("thresholds_by_context", {})
    ctx = context or {}
    if ctx.get("pregnancy") is not True:
        return False
    trimester = ctx.get("trimester")
    if trimester in (1, 2, 3) and f"pregnancy_T{trimester}" in by_context:
        return True
    return "pregnancy" in by_context


def elderly_thresholds_in_use(lab_def: dict, context: dict | None) -> bool:
    """True iff pick_thresholds will pick the elderly-specific band set
    (age >= ELDERLY_AGE_THRESHOLD, no pregnancy override)."""
    if "thresholds" in lab_def:
        return False
    if pregnancy_thresholds_in_use(lab_def, context):
        return False
    by_context = lab_def.get("thresholds_by_context", {})
    age = (context or {}).get("age")
    return (
        age is not None
        and age >= ELDERLY_AGE_THRESHOLD
        and "elderly" in by_context
    )


def find_severity(value: float, thresholds: list[dict]) -> str:
    """Find the severity tier the value falls into.

    Uses [min, max) half-open intervals. A threshold may have only `min`,
    only `max`, or both. Returns 'Unknown' if no tier matches (shouldn't
    happen with a well-formed rules file).
    """
    for t in thresholds:
        lo = t.get("min")
        hi = t.get("max")
        if lo is not None and value < lo:
            continue
        if hi is not None and value >= hi:
            continue
        return t["severity"]
    return "Unknown"


_SLOT_PATTERN = re.compile(r"\{(\w+)\}")


def render_template(text: str, slots: dict[str, Any]) -> str:
    """Substitute {slot} tokens with values from slots.

    Unknown or None slots pass through unchanged. [bracket] placeholders
    are intentionally left for the IDC to fill in by hand.
    """
    def replace(m: re.Match[str]) -> str:
        key = m.group(1)
        val = slots.get(key)
        if val is None or val == "":
            return m.group(0)
        return str(val)
    return _SLOT_PATTERN.sub(replace, text)


def render_follow_up(follow_up: dict, slots: dict[str, Any]) -> dict:
    """Render template slots in a follow_up dict."""
    return {
        "category": render_template(follow_up.get("category", ""), slots),
        "next_tests": [render_template(t, slots) for t in follow_up.get("next_tests", [])],
        "ehr_plan": render_template(follow_up.get("ehr_plan", ""), slots),
        "patient_communication": render_template(follow_up.get("patient_communication", ""), slots),
    }


def pick_follow_up_dict(lab_def: dict, context: dict | None) -> tuple[dict, str | None]:
    """Pick the follow_up dict (severity -> {category, next_tests, ehr_plan, patient_communication}).

    Returns (follow_up_dict, branch_label). branch_label is the context branch
    used (e.g. 'diabetic', 'default') or None if the lab uses a single follow_up.
    """
    if "follow_up_by_context" in lab_def:
        fubc = lab_def["follow_up_by_context"]
        diabetic = (context or {}).get("diabetic")
        if diabetic is True and "diabetic" in fubc:
            return fubc["diabetic"], "diabetic"
        return fubc.get("default", {}), "default"
    return lab_def.get("follow_up", {}), None


def evaluate(
    lab_id: str,
    value: float,
    rules: dict,
    context: dict | None = None,
    priors: list | None = None,
) -> dict:
    """Evaluate a single lab value and return a structured result.

    Result keys: lab_id, display_name, value, unit, severity, follow_up,
    follow_up_branch, threshold_used_default, differentiation, thresholds,
    sources. On unknown lab_id returns {lab_id, value, error}.

    If `priors` is supplied (list of PriorValue, (value, date_str) tuples,
    or {"value": ..., "date_str": ...} dicts), a `trend` block is attached
    to the result with velocity / delta / direction / baseline metadata.
    Lab-specific trend interpretation text comes from `interpret_trend`.
    """
    lab_def = rules.get("labs", {}).get(lab_id)
    if not lab_def:
        return {"lab_id": lab_id, "value": value, "error": f"Unknown lab: {lab_id}"}

    thresholds, used_default = pick_thresholds(lab_def, context)
    severity = find_severity(value, thresholds)
    follow_up_dict, branch = pick_follow_up_dict(lab_def, context)
    follow_up_def = follow_up_dict.get(severity)

    slots: dict[str, Any] = {
        "value": value,
        "unit": lab_def.get("unit", ""),
        **(context or {}),
    }
    rendered = render_follow_up(follow_up_def, slots) if follow_up_def else None

    trend = compute_trend_metrics(value, priors)
    if trend["available"]:
        trend["interpretation"] = interpret_trend(lab_id, value, trend, lab_def)

    return {
        "lab_id": lab_id,
        "display_name": lab_def.get("display_name", lab_id),
        "value": value,
        "unit": lab_def.get("unit", ""),
        "severity": severity,
        "follow_up": rendered,
        "follow_up_branch": branch,
        "threshold_used_default": used_default,
        "pregnancy_thresholds": pregnancy_thresholds_in_use(lab_def, context),
        "elderly_thresholds": elderly_thresholds_in_use(lab_def, context),
        "differentiation": lab_def.get("differentiation"),
        "thresholds": thresholds,
        "sources": lab_def.get("sources", []),
        "trend": trend,
    }


def _interpret_psa_trend(current: float, m: dict) -> str | None:
    """PSA velocity > 0.75 ng/mL/year is the classic threshold for further
    workup even when the absolute value is within reference range
    (Carter et al.; AUA 2023 guidance acknowledges velocity as adjunct)."""
    velocity = m.get("velocity_per_year")
    span_y = m.get("span_years")
    direction = m.get("direction")
    if velocity is None:
        return None
    baseline = m.get("baseline_value")
    if velocity > 0.75:
        return (
            f"PSA velocity = +{velocity} ng/mL/year over {span_y} y "
            f"(prior {baseline} ng/mL on {m['baseline_date']}, current "
            f"{current} ng/mL). Rate >0.75/year warrants urology referral "
            "even within reference range — calculate PSA density and "
            "consider multiparametric prostate MRI."
        )
    if velocity < -0.5:
        return (
            f"PSA velocity = {velocity} ng/mL/year — declining trend "
            f"(prior {baseline} on {m['baseline_date']}). Consistent with "
            "treatment response if on 5α-reductase inhibitor or post-RP / "
            "radiation; document trajectory."
        )
    if direction == "rising":
        return (
            f"PSA rising slowly: +{m['delta']} ng/mL over {span_y} y "
            f"(velocity {velocity}/year, below 0.75 threshold). Continue "
            "surveillance per AUA 2023; consider repeat in 6–12 months."
        )
    return f"PSA stable since {m['baseline_date']} (Δ {m['delta']:+}; velocity {velocity}/year)."


def _interpret_cr_trend(current: float, m: dict) -> str | None:
    """Cr trend with KDIGO AKI overlay. When the most-recent prior is
    within the 7-day KDIGO window, treats it as the baseline and reports
    the AKI stage; for older priors, describes trajectory only."""
    span_d = m.get("span_days")
    delta = m.get("delta")
    baseline = m.get("baseline_value")
    if span_d is None or delta is None or baseline is None or baseline <= 0:
        return None
    if span_d <= 7:
        ratio = current / baseline
        if ratio >= 3.0 or current >= 4.0:
            stage = "Stage 3 AKI"
        elif ratio >= 2.0:
            stage = "Stage 2 AKI"
        elif ratio >= 1.5 or (span_d <= 2 and delta >= 0.3):
            stage = "Stage 1 AKI"
        else:
            stage = "No AKI by KDIGO"
        return (
            f"Cr trend: prior {baseline} mg/dL ({span_d}d ago) → current "
            f"{current} (ratio {round(ratio, 2)}, Δ {delta:+} mg/dL). "
            f"KDIGO: {stage}."
        )
    if delta >= 0.3:
        return (
            f"Cr trending up: {baseline} → {current} mg/dL over "
            f"{m['span_years']} y (Δ +{delta}). Re-assess kidney function "
            "(repeat eGFR, UACR; review nephrotoxic medications)."
        )
    if delta <= -0.3:
        return (
            f"Cr trending down: {baseline} → {current} mg/dL over "
            f"{m['span_years']} y. Consistent with improving volume status, "
            "treatment response, or muscle-mass loss — clinical correlation."
        )
    return f"Cr stable since {m['baseline_date']} (Δ {delta:+} over {m['span_years']} y)."


def _interpret_a1c_trend(current: float, m: dict) -> str | None:
    """A1C — ADA Standards of Care: ≥0.5% change is clinically meaningful."""
    delta = m.get("delta")
    span_y = m.get("span_years")
    baseline = m.get("baseline_value")
    if delta is None or baseline is None:
        return None
    if delta <= -0.5:
        return (
            f"A1C improving by {abs(delta)}% over {span_y} y "
            f"({baseline}% → {current}%). Maintain regimen; reinforce "
            "lifestyle gains; reassess goal per ADA Standards of Care."
        )
    if delta >= 0.5:
        return (
            f"A1C worsening by {delta}% over {span_y} y "
            f"({baseline}% → {current}%). Reassess medication adherence, "
            "diet, weight, glucotoxicity / lipotoxicity; consider "
            "intensification per ADA Standards of Care."
        )
    return (
        f"A1C stable (Δ {delta:+}% over {span_y} y); current {current}%."
    )


def _interpret_k_trend(current: float, m: dict) -> str | None:
    """Potassium — distinguishes acute swings (medication / GI / cardiac
    risk) from chronic drift (CKD progression, chronic diuretic burden)."""
    span_d = m.get("span_days")
    delta = m.get("delta")
    baseline = m.get("baseline_value")
    if span_d is None or delta is None or baseline is None:
        return None
    direction = m.get("direction")
    if span_d <= 14 and delta >= 0.5:
        return (
            f"K trending up acutely: {baseline} → {current} mEq/L over "
            f"{span_d}d (Δ +{delta}). Review ACEi / ARB / spironolactone / "
            "K-supplements / NSAIDs; ECG if K ≥5.5; recheck non-hemolyzed."
        )
    if span_d <= 14 and delta <= -0.5:
        return (
            f"K trending down acutely: {baseline} → {current} mEq/L over "
            f"{span_d}d (Δ {delta}). Review GI losses (vomiting / diarrhea), "
            "thiazide / loop diuretic, insulin / β-agonist; check Mg "
            "(refractory K is often hypomagnesemic)."
        )
    if direction == "rising":
        return (
            f"K chronic uptrend: {baseline} → {current} mEq/L over "
            f"{m['span_years']} y. Reassess CKD progression, medication "
            "burden, dietary K; consider K-binder if persistent ≥5.5 with "
            "essential RAAS therapy."
        )
    if direction == "falling":
        return (
            f"K chronic downtrend: {baseline} → {current} mEq/L over "
            f"{m['span_years']} y. Reassess chronic diuretic use, "
            "nutritional intake; check Mg."
        )
    return f"K stable since {m['baseline_date']} (Δ {delta:+} over {m['span_years']} y)."


def _interpret_hgb_trend(current: float, m: dict) -> str | None:
    """Hgb — acute drops trigger bleeding / hemolysis workup; chronic
    drops are workup-by-MCV (already shipped); recovery is treatment
    response."""
    span_d = m.get("span_days")
    delta = m.get("delta")
    baseline = m.get("baseline_value")
    if span_d is None or delta is None or baseline is None:
        return None
    if span_d <= 14 and delta <= -1.0:
        return (
            f"Hgb dropped {abs(delta)} g/dL over {span_d}d ({baseline} → "
            f"{current}). Acute drop warrants bleeding workup (stool guaiac, "
            "GI evaluation, type & screen), hemolysis labs (LDH, haptoglobin, "
            "indirect bili, retic), and hemodynamic / orthostatic check."
        )
    if span_d <= 14 and delta >= 1.0:
        return (
            f"Hgb rose {delta} g/dL over {span_d}d ({baseline} → {current}) "
            "— consistent with transfusion or rapid volume contraction; "
            "check post-transfusion CBC + 24-hour stability."
        )
    if delta <= -1.0:
        return (
            f"Hgb chronic decline: {baseline} → {current} g/dL over "
            f"{m['span_years']} y. MCV-based anemia workup (iron studies, "
            "B12 / folate, retic, peripheral smear); GI evaluation if "
            "iron-deficient adult male or post-menopausal female."
        )
    if delta >= 1.0:
        return (
            f"Hgb chronic improvement: {baseline} → {current} g/dL — "
            "consistent with iron / B12 / folate replacement, EPO therapy, "
            "or resolution of underlying disease."
        )
    return f"Hgb stable since {m['baseline_date']} (Δ {delta:+} g/dL)."


def _interpret_alt_trend(current: float, m: dict) -> str | None:
    """ALT — distinguishes resolving acute hepatitis from persistent
    elevation (chronic viral / MASLD / autoimmune)."""
    span_d = m.get("span_days")
    delta = m.get("delta")
    baseline = m.get("baseline_value")
    delta_pct = m.get("delta_pct")
    if span_d is None or delta is None or baseline is None or baseline <= 0:
        return None
    # Improvement: large drop, especially within months
    if delta_pct is not None and delta_pct <= -50:
        return (
            f"ALT improving substantially: {baseline} → {current} U/L over "
            f"{m['span_years']} y ({delta_pct}%). Consistent with resolving "
            "acute hepatitis (drug-induced, viral, ischemic) — continue "
            "monitoring until normalized; review timing relative to "
            "withdrawn agent / viral clearance."
        )
    # Persistent elevation > 6 months: chronic
    if span_d >= 180 and current > baseline * 0.7:
        return (
            f"ALT persistently elevated: {baseline} → {current} U/L over "
            f"{m['span_years']} y. Persistent ≥6 months warrants FIB-4, "
            "MASLD case-finding (BMI / A1C / lipids), HBV / HCV serology, "
            "second-tier workup (iron studies, ANA / ASMA / IgG, "
            "ceruloplasmin if <40, A1AT)."
        )
    if delta_pct is not None and delta_pct >= 50:
        return (
            f"ALT worsening: {baseline} → {current} U/L over "
            f"{m['span_years']} y ({delta_pct:+}%). Reassess hepatotoxic "
            "exposures, alcohol, new medications, viral hepatitis."
        )
    return f"ALT relatively stable since {m['baseline_date']} (Δ {delta:+} U/L)."


def _interpret_ldl_trend(current: float, m: dict) -> str | None:
    """LDL — primary treatment-response marker. Per ACC/AHA, high-intensity
    statin should produce ≥50% LDL reduction; moderate-intensity 30–49%."""
    delta_pct = m.get("delta_pct")
    baseline = m.get("baseline_value")
    span_y = m.get("span_years")
    if delta_pct is None or baseline is None:
        return None
    if delta_pct <= -50:
        return (
            f"LDL improved ≥50%: {baseline} → {current} mg/dL ({delta_pct}%) "
            f"over {span_y} y. Consistent with high-intensity statin response "
            "per ACC/AHA — continue regimen and reassess yearly."
        )
    if delta_pct <= -30:
        return (
            f"LDL improved 30–49%: {baseline} → {current} mg/dL ({delta_pct}%) "
            f"over {span_y} y. Consistent with moderate-intensity statin "
            "response. If 10-yr ASCVD ≥7.5% or other risk-enhancing factors, "
            "consider intensification per ACC/AHA."
        )
    if delta_pct >= 20:
        return (
            f"LDL worsening: {baseline} → {current} mg/dL ({delta_pct:+}%) "
            f"over {span_y} y. Reassess statin adherence, diet, weight, "
            "secondary causes (hypothyroidism, nephrotic syndrome, "
            "cholestasis); consider PCSK9 / ezetimibe addition if at goal "
            "previously."
        )
    return (
        f"LDL relatively stable: {baseline} → {current} mg/dL "
        f"({delta_pct:+}%) over {span_y} y."
    )


def _interpret_tsh_trend(current: float, m: dict) -> str | None:
    """TSH — primary monitor for thyroid replacement / antithyroid Rx."""
    delta = m.get("delta")
    baseline = m.get("baseline_value")
    span_y = m.get("span_years")
    if delta is None or baseline is None:
        return None
    # Hypothyroid replacement target: TSH 0.4-4.0 typically
    if baseline > 4.0 and current <= 4.0:
        return (
            f"TSH normalized: {baseline} → {current} mIU/L over {span_y} y. "
            "Consistent with adequate levothyroxine replacement — recheck "
            "TSH in 6–8 weeks after any dose change, then every 6–12 months."
        )
    if baseline > 4.0 and current > baseline:
        return (
            f"TSH worsening on therapy: {baseline} → {current} mIU/L. "
            "Reassess levothyroxine adherence, timing (empty stomach, away "
            "from calcium / iron / coffee), drug interactions (PPI, "
            "estrogen, anticonvulsants), absorption (celiac); recheck "
            "free T4."
        )
    # Hyperthyroid suppression target on antithyroid Rx
    if baseline < 0.4 and current >= 0.4:
        return (
            f"TSH recovering: {baseline} → {current} mIU/L. Consistent with "
            "antithyroid medication response or thyroiditis resolution; "
            "free T4 + free T3; titrate dose per endocrinology."
        )
    if abs(delta) < 0.5:
        return f"TSH stable since {m['baseline_date']} (Δ {delta:+} mIU/L)."
    return (
        f"TSH change: {baseline} → {current} mIU/L over {span_y} y "
        f"(Δ {delta:+}). Correlate with treatment changes and free T4."
    )


_TREND_INTERPRETERS = {
    "psa": _interpret_psa_trend,
    "creatinine": _interpret_cr_trend,
    "hba1c": _interpret_a1c_trend,
    "potassium": _interpret_k_trend,
    "hemoglobin": _interpret_hgb_trend,
    "alt": _interpret_alt_trend,
    "ldl_cholesterol": _interpret_ldl_trend,
    "tsh": _interpret_tsh_trend,
}


def interpret_trend(
    lab_id: str,
    current_value: float,
    metrics: dict,
    lab_def: dict,
) -> str | None:
    """Return a lab-specific narrative for the trend metrics, or None
    if no trend interpretation is defined for this lab. The numeric
    metrics already include velocity / delta / direction; this layer
    adds clinical meaning (PSA velocity threshold, A1C improvement
    cutoff, KDIGO AKI ratio, etc.).

    Adding a new interpreter: write a `_interpret_<lab>_trend(current,
    metrics) -> str | None` function and register it in
    _TREND_INTERPRETERS. The dispatch is intentionally explicit — each
    lab's clinical thresholds differ and shouldn't be inferred from
    rules.json magic.
    """
    if not metrics.get("available"):
        return None
    interp = _TREND_INTERPRETERS.get(lab_id)
    if interp is None:
        return None
    return interp(current_value, metrics)


# ---------- Serology / qualitative interpreters ----------


def evaluate_serology(
    lab_id: str, inputs: dict, rules: dict
) -> dict:
    """Match boolean serology marker inputs to a labelled clinical pattern.

    Patterns in rules.json are listed in match-priority order. For each
    pattern, all marker keys in `match` must equal the input value; markers
    not in `match` are wildcards. Inputs may be True, False, or None
    (None = not done, treats the marker as wildcard for matching).

    On no pattern match, returns the lab's `fallback` block (typically
    "indeterminate"). The result also lists any markers that were left
    None so the UI can prompt the IDC to fill them in.
    """
    lab_def = rules.get("labs", {}).get(lab_id)
    if not lab_def or lab_def.get("kind") != "serology":
        return {
            "lab_id": lab_id,
            "error": f"Not a serology lab: {lab_id}",
        }

    expected_inputs = [i["id"] for i in lab_def.get("inputs", [])]
    missing = [i for i in expected_inputs if inputs.get(i) is None]

    matched = None
    for pattern in lab_def.get("patterns", []):
        constraints = pattern.get("match", {})
        if all(inputs.get(k) == v for k, v in constraints.items()):
            matched = pattern
            break

    if matched is None:
        matched = lab_def.get("fallback", {"id": "indeterminate", "label": "Indeterminate"})

    return {
        "lab_id": lab_id,
        "kind": "serology",
        "display_name": lab_def.get("display_name", lab_id),
        "pattern_id": matched.get("id"),
        "pattern_label": matched.get("label"),
        "category": matched.get("category"),
        "next_tests": matched.get("next_tests", []),
        "ehr_plan": matched.get("ehr_plan", ""),
        "patient_communication": matched.get("patient_communication", ""),
        "missing_inputs": missing,
        "inputs": dict(inputs),
        "sources": lab_def.get("sources", []),
    }


# ---------- Panel-level derived computations ----------


def compute_egfr(creatinine: float | None, age: int | None, sex: str | None) -> float | None:
    """CKD-EPI 2021 eGFR (no race coefficient).

    Requires Cr (mg/dL), age (years), and sex ('female' or 'male'). Returns
    None if any input is missing or invalid.

    Formula: GFR = 142 × min(Scr/κ, 1)^α × max(Scr/κ, 1)^-1.200
                   × 0.9938^Age × (1.012 if female else 1.000)
    where κ = 0.7 (female) or 0.9 (male); α = -0.241 (female) or -0.302 (male).
    """
    if creatinine is None or creatinine <= 0:
        return None
    if not age or age <= 0:
        return None
    if sex not in ("female", "male"):
        return None

    if sex == "female":
        kappa, alpha, sex_factor = 0.7, -0.241, 1.012
    else:
        kappa, alpha, sex_factor = 0.9, -0.302, 1.000

    cr_kappa = creatinine / kappa
    egfr = (
        142
        * (min(cr_kappa, 1.0) ** alpha)
        * (max(cr_kappa, 1.0) ** -1.200)
        * (0.9938 ** age)
        * sex_factor
    )
    return round(egfr, 1)


def assign_ckd_g_stage(egfr: float | None) -> str | None:
    """KDIGO G stage from eGFR (mL/min/1.73 m²)."""
    if egfr is None:
        return None
    if egfr >= 90:
        return "G1"
    if egfr >= 60:
        return "G2"
    if egfr >= 45:
        return "G3a"
    if egfr >= 30:
        return "G3b"
    if egfr >= 15:
        return "G4"
    return "G5"


def assign_ckd_a_stage(acr: float | None) -> str | None:
    """KDIGO A stage from urine albumin/creatinine ratio (mg/g)."""
    if acr is None:
        return None
    if acr < 30:
        return "A1"
    if acr < 300:
        return "A2"
    return "A3"


def chronic_ckd_labs_indicated(g_stage: str | None) -> bool:
    """True at G3a or worse — KDIGO recommends starting CKD chronic labs."""
    return g_stage in {"G3a", "G3b", "G4", "G5"}


def compute_kdigo_aki_stage(
    current_cr: float | None, baseline_cr: float | None
) -> str | None:
    """KDIGO 2012 AKI staging based on Cr ratio + absolute change.

    Returns 'Stage 1', 'Stage 2', 'Stage 3', 'No AKI', or None if not computable.
    Time-window of <48 h (for +0.3 mg/dL) and 7 d (for ratio) is assumed
    rather than enforced — this is a snapshot calculation, not a longitudinal one.
    """
    if current_cr is None or baseline_cr is None or baseline_cr <= 0:
        return None
    delta = current_cr - baseline_cr
    ratio = current_cr / baseline_cr
    if ratio >= 3.0 or current_cr >= 4.0:
        return "Stage 3"
    if ratio >= 2.0:
        return "Stage 2"
    if ratio >= 1.5 or delta >= 0.3:
        return "Stage 1"
    return "No AKI"


def compute_bun_cr_ratio(bun: float | None, cr: float | None) -> float | None:
    if bun is None or cr is None or cr <= 0:
        return None
    return round(bun / cr, 1)


def interpret_bun_cr_ratio(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    if ratio > 20:
        return (
            f"BUN/Cr ratio {ratio} (>20) — suggestive of prerenal azotemia "
            "(volume depletion, GI bleed, high protein intake) or postrenal "
            "obstruction. Consider hydration assessment, stool occult blood, "
            "and urinalysis."
        )
    if ratio < 10:
        return (
            f"BUN/Cr ratio {ratio} (<10) — suggestive of intrinsic renal "
            "disease, malnutrition, low protein intake, or liver disease."
        )
    return f"BUN/Cr ratio {ratio} — within normal range (10–20)."


def compute_anion_gap(
    na: float | None, cl: float | None, hco3: float | None
) -> float | None:
    """Anion gap = Na − (Cl + HCO3). Normal 8–12."""
    if na is None or cl is None or hco3 is None:
        return None
    return round(na - cl - hco3, 1)


# ---------- LFT pattern (R-factor) ----------

# Sex-specific ALT ULN matching rules.json Mild-High cutoffs
# (lab-reported ULN per ACG 2017). Default to male ULN when sex unknown
# to be permissive — under-flagging an unknown patient is preferable to
# over-flagging when sex isn't documented.
_ALT_ULN: dict[str, float] = {"female": 33.0, "male": 42.0}
_ALT_ULN_DEFAULT = 42.0
_ALP_ULN = 130.0  # adult, non-pregnancy; matches rules.json Normal upper bound


def compute_lft_r_factor(
    alt: float | None, alp: float | None, sex: str | None
) -> float | None:
    """R-factor for liver-injury pattern classification.

    R = (ALT / ALT_ULN) / (ALP / ALP_ULN). Used per AASLD/EASL DILI and
    cholestatic-disease guidance to differentiate hepatocellular vs
    cholestatic vs mixed injury when one or both enzymes are elevated.

    Returns None when ALT or ALP is missing/non-positive, or when both
    are within their ULN (R-factor isn't clinically meaningful in that
    case — there's no injury to classify).
    """
    if alt is None or alp is None or alt <= 0 or alp <= 0:
        return None
    alt_uln = _ALT_ULN.get(sex or "", _ALT_ULN_DEFAULT)
    if alt < alt_uln and alp < _ALP_ULN:
        return None
    return round((alt / alt_uln) / (alp / _ALP_ULN), 2)


def classify_lft_pattern(r: float | None) -> str | None:
    """AASLD/EASL R-factor pattern classification:
    R > 5 → hepatocellular, R < 2 → cholestatic, 2 ≤ R ≤ 5 → mixed."""
    if r is None:
        return None
    if r > 5.0:
        return "hepatocellular"
    if r < 2.0:
        return "cholestatic"
    return "mixed"


def interpret_lft_pattern(pattern: str | None, r: float | None) -> str | None:
    if pattern is None or r is None:
        return None
    if pattern == "hepatocellular":
        return (
            f"R = {r} (>5) — hepatocellular pattern. Workup: viral hepatitis "
            "(HBV, HCV; HAV/HEV if acute), drug/supplement review including "
            "acetaminophen, alcohol screen, MASLD case-finding (BMI, A1C, "
            "lipids), autoimmune (ANA, ASMA, IgG), iron studies, ceruloplasmin "
            "if age <40, A1AT. FIB-4 if persistent."
        )
    if pattern == "cholestatic":
        return (
            f"R = {r} (<2) — cholestatic pattern. Workup: GGT to confirm "
            "hepatic origin of ALP elevation; RUQ ultrasound (gallstones, "
            "biliary dilation, mass); MRCP if intra/extrahepatic obstruction "
            "suspected; AMA for primary biliary cholangitis; drug review "
            "(estrogens, anabolic steroids, antibiotics)."
        )
    return (
        f"R = {r} (2–5) — mixed hepatocellular/cholestatic pattern. "
        "Pursue both hepatocellular and cholestatic workups in parallel: "
        "viral hepatitis serology, MASLD risk stratification, GGT, RUQ "
        "ultrasound, drug/supplement review."
    )


# ---------- Anemia workup branching (MCV-driven) ----------


def classify_anemia_by_mcv(mcv: float | None) -> str | None:
    """Classify anemia by MCV. Standard cutoffs: <80 microcytic, 80–100
    normocytic, >100 macrocytic. Caller decides whether to invoke this
    (only meaningful when Hgb is below normal)."""
    if mcv is None or mcv <= 0:
        return None
    if mcv < 80:
        return "microcytic"
    if mcv > 100:
        return "macrocytic"
    return "normocytic"


def interpret_anemia_workup(
    pattern: str | None, mcv: float | None
) -> str | None:
    """Pattern-specific anemia workup guidance. mcv is included in the
    text so the IDC sees which side of the cutoff the value falls on."""
    if pattern is None or mcv is None:
        return None
    if pattern == "microcytic":
        return (
            f"MCV {mcv} fL (<80) — microcytic anemia. Workup: ferritin, "
            "iron, TIBC, transferrin saturation (iron deficiency is the "
            "most common cause; ferritin <30 ng/mL confirms). If iron "
            "studies normal — hemoglobin electrophoresis (thalassemia, "
            "especially Mediterranean / SE Asian / African descent), "
            "consider lead level and anemia of chronic disease (CRP, "
            "ferritin paradoxically normal/high). Stool occult blood and "
            "GI workup if iron deficiency confirmed in adult male or "
            "post-menopausal female."
        )
    if pattern == "macrocytic":
        return (
            f"MCV {mcv} fL (>100) — macrocytic anemia. Workup: B12 and "
            "folate (megaloblastic if either deficient); TSH "
            "(hypothyroidism); peripheral smear (hypersegmented "
            "neutrophils confirm megaloblastic); reticulocyte count; "
            "alcohol-use screen; medication review (methotrexate, "
            "hydroxyurea, zidovudine, phenytoin). MCV >115 strongly "
            "suggests B12/folate; MCV 100–115 broaden to alcohol, "
            "hypothyroidism, MDS, drug-induced."
        )
    return (
        f"MCV {mcv} fL (80–100) — normocytic anemia. Workup: reticulocyte "
        "count to separate hypoproliferative (low retic — chronic "
        "disease, early iron deficiency, renal, marrow failure) from "
        "hyperproliferative (high retic — acute blood loss, hemolysis); "
        "peripheral smear; haptoglobin and LDH if hemolysis suspected "
        "(low haptoglobin + high LDH); CMP (renal); TSH; ferritin (early "
        "iron deficiency can be normocytic before becoming microcytic)."
    )


def correct_calcium_for_albumin(
    ca: float | None, albumin: float | None
) -> float | None:
    """Albumin-corrected calcium.

    Formula: Ca_corr = Ca + 0.8 × (4.0 − albumin), with Ca in mg/dL and
    albumin in g/dL. Hypoalbuminemia depresses total Ca without changing
    ionized Ca, so the measured total can read as low even when ionized Ca
    is normal. Returns None if either input is missing or non-positive.
    """
    if ca is None or albumin is None or ca <= 0 or albumin <= 0:
        return None
    return round(ca + 0.8 * (4.0 - albumin), 2)


def _load_pyprevent():
    """Import pyprevent, with recovery for the 0.1.5 wheel packaging bug.

    pyprevent 0.1.5 installs its compiled extension as
    `pyprevent.cpython-<tag>.so` instead of `_pyprevent.cpython-<tag>.so`,
    so `from pyprevent import _pyprevent` raises ImportError on affected
    environments (notably Linux/Python 3.11 — including the project CI).
    The .so itself is correctly built and exports the expected Rust
    functions, so we locate it on disk and inject it as the missing
    `pyprevent._pyprevent` submodule, then retry the package import.
    Returns None if pyprevent isn't installed at all or recovery fails.
    """
    try:
        import pyprevent  # type: ignore[import-untyped]
        return pyprevent
    except ImportError:
        pass

    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.find_spec("pyprevent")
    if spec is None or not spec.submodule_search_locations:
        return None
    pkg_dir = Path(next(iter(spec.submodule_search_locations)))

    for so_path in pkg_dir.glob("*.so"):
        if so_path.stem.startswith("_pyprevent"):
            continue
        sub_spec = importlib.util.spec_from_file_location(
            "pyprevent._pyprevent", so_path
        )
        if sub_spec is None or sub_spec.loader is None:
            continue
        sub_mod = importlib.util.module_from_spec(sub_spec)
        try:
            sub_spec.loader.exec_module(sub_mod)
        except Exception:  # noqa: BLE001
            continue
        if not hasattr(sub_mod, "calculate_10_yr_ascvd_rust"):
            continue
        sys.modules["pyprevent._pyprevent"] = sub_mod
        try:
            import pyprevent  # type: ignore[import-untyped]
            return pyprevent
        except ImportError:
            return None
    return None


def compute_prevent_risk(
    context: dict | None,
    values_by_lab: dict,
    egfr: float | None,
) -> dict:
    """Compute AHA PREVENT 2023 10-year risks if inputs are available.

    Pulls inputs from context (sex, age, systolic_bp, current_smoker, bmi,
    on_htn_meds, on_cholesterol_meds, diabetic) and from session lab values
    (total_cholesterol, hdl_cholesterol). eGFR comes from the panel-level
    derived computation.

    Returns a dict with availability flag, lists of missing / out-of-range
    inputs, the three 10-year risks (ASCVD, CVD, HF), a risk tier, and a
    statin-intensity recommendation per the 2026 ACC/AHA dyslipidemia guideline.
    Lazy-imports pyprevent so the engine doesn't pay the import cost when
    PREVENT isn't being used.
    """
    ctx = context or {}
    sex = ctx.get("sex")
    age = ctx.get("age")
    sbp = ctx.get("systolic_bp")
    smoker = ctx.get("current_smoker")
    bmi = ctx.get("bmi")
    on_htn = ctx.get("on_htn_meds")
    on_lipid = ctx.get("on_cholesterol_meds")
    diabetic = ctx.get("diabetic")

    tc = values_by_lab.get("total_cholesterol")
    hdl = values_by_lab.get("hdl_cholesterol")

    missing: list[str] = []
    if sex not in ("male", "female"):
        missing.append("sex")
    if not age:
        missing.append("age")
    if tc is None:
        missing.append("total cholesterol")
    if hdl is None:
        missing.append("HDL cholesterol")
    if sbp is None:
        missing.append("systolic BP")
    if bmi is None:
        missing.append("BMI")
    if egfr is None:
        missing.append("eGFR (requires creatinine + age + sex)")

    empty_result = {
        "available": False,
        "missing": missing,
        "out_of_range": [],
        "ascvd_10y": None,
        "cvd_10y": None,
        "hf_10y": None,
        "risk_tier": None,
        "statin_recommendation": None,
    }
    if missing:
        return empty_result

    pyprevent = _load_pyprevent()
    if pyprevent is None:
        empty_result["out_of_range"] = ["pyprevent not installed"]
        return empty_result

    kwargs = dict(
        sex=sex,
        age=float(age),
        total_cholesterol=float(tc),
        hdl_cholesterol=float(hdl),
        systolic_bp=float(sbp),
        has_diabetes=bool(diabetic),
        current_smoker=bool(smoker),
        bmi=float(bmi),
        egfr=float(egfr),
        on_htn_meds=bool(on_htn),
        on_cholesterol_meds=bool(on_lipid),
    )

    try:
        ascvd = pyprevent.calculate_10_yr_ascvd_risk(**kwargs)
        cvd = pyprevent.calculate_10_yr_cvd_risk(**kwargs)
        hf = pyprevent.calculate_10_yr_heart_failure_risk(**kwargs)
    except ValueError as e:
        return {
            "available": False,
            "missing": [],
            "out_of_range": [str(e)],
            "ascvd_10y": None,
            "cvd_10y": None,
            "hf_10y": None,
            "risk_tier": None,
            "statin_recommendation": None,
        }

    if ascvd >= 10:
        tier = "high"
        rec = (
            "10-yr ASCVD ≥10% — high-intensity statin (atorvastatin 40–80 mg "
            "or rosuvastatin 20–40 mg). LDL target <70 mg/dL or ≥50% reduction."
        )
    elif ascvd >= 3:
        tier = "intermediate"
        rec = (
            "10-yr ASCVD 3–10% — moderate-intensity statin (atorvastatin 10–20, "
            "rosuvastatin 5–10, simvastatin 20–40). Discuss risk-enhancing factors "
            "(family hx, CKD, CAC scoring) for shared decision."
        )
    else:
        tier = "low"
        rec = (
            "10-yr ASCVD <3% — generally lifestyle counseling. Consider "
            "moderate-intensity statin if LDL 160–189 or 30-yr ASCVD ≥10%. "
            "LDL ≥190 always warrants high-intensity statin and FH workup "
            "regardless of computed risk."
        )

    return {
        "available": True,
        "missing": [],
        "out_of_range": [],
        "ascvd_10y": round(ascvd, 1),
        "cvd_10y": round(cvd, 1),
        "hf_10y": round(hf, 1),
        "risk_tier": tier,
        "statin_recommendation": rec,
    }


def evaluate_panel(
    lab_inputs: list[tuple[str, float]],
    rules: dict,
    context: dict | None = None,
    priors_by_lab: dict | None = None,
) -> dict:
    """Evaluate a list of (lab_id, value) inputs and compute derived values.

    Returns:
        {
            "results": [evaluate(...) results, in input order],
            "derived": {
                "bun_cr_ratio": float | None,
                "bun_cr_ratio_interpretation": str | None,
                "anion_gap": float | None,
                "egfr": float | None,
                "egfr_formula": str,
                "ckd_g_stage": str | None,
                "ckd_a_stage": str | None,
                "ckd_ga_stage": str | None,    # 'G3aA2' if both present, else None
                "kdigo_aki_stage": str | None,
                "chronic_ckd_labs_indicated": bool,
                "missing_for_ckd_staging": [str],
            }
        }
    """
    priors_by_lab = priors_by_lab or {}
    results = [
        evaluate(lab_id, value, rules, context, priors=priors_by_lab.get(lab_id))
        for lab_id, value in lab_inputs
    ]
    values_by_lab = {
        r["lab_id"]: r["value"] for r in results if "lab_id" in r and "error" not in r
    }
    ctx = context or {}

    bun = values_by_lab.get("bun")
    cr = values_by_lab.get("creatinine")
    na = values_by_lab.get("sodium")
    cl = values_by_lab.get("chloride")
    hco3 = values_by_lab.get("bicarbonate")
    ca = values_by_lab.get("calcium")
    albumin = values_by_lab.get("albumin")
    alt = values_by_lab.get("alt")
    alp = values_by_lab.get("alkaline_phosphatase")
    mcv = values_by_lab.get("mcv")
    age = ctx.get("age")
    sex = ctx.get("sex")
    baseline_cr = ctx.get("baseline_creatinine")
    acr = ctx.get("urine_acr")

    hgb_severity: str | None = next(
        (
            r["severity"] for r in results
            if r.get("lab_id") == "hemoglobin" and "severity" in r
        ),
        None,
    )
    is_anemic = hgb_severity in {
        "Mild Low", "Moderate Low", "Severe Low", "Critical Low"
    }
    anemia_pattern = (
        classify_anemia_by_mcv(mcv) if (is_anemic and mcv is not None) else None
    )

    egfr = compute_egfr(cr, age, sex) if cr is not None else None
    g_stage = assign_ckd_g_stage(egfr)
    a_stage = assign_ckd_a_stage(acr)
    ga_stage = (g_stage + a_stage) if (g_stage and a_stage) else None
    aki_stage = compute_kdigo_aki_stage(cr, baseline_cr) if cr is not None else None
    bun_cr = compute_bun_cr_ratio(bun, cr)
    ag = compute_anion_gap(na, cl, hco3)
    lft_r = compute_lft_r_factor(alt, alp, sex)
    lft_pattern = classify_lft_pattern(lft_r)
    corrected_ca = correct_calcium_for_albumin(ca, albumin)
    if corrected_ca is not None and abs(corrected_ca - ca) >= 0.1:
        correction_eval = evaluate("calcium", corrected_ca, rules, context)
        for r in results:
            if r.get("lab_id") == "calcium":
                r["correction"] = {
                    "type": "albumin_corrected",
                    "measured_value": ca,
                    "value": corrected_ca,
                    "albumin": albumin,
                    "severity": correction_eval["severity"],
                    "follow_up": correction_eval["follow_up"],
                    "formula": "Ca_corr = Ca + 0.8 × (4.0 − albumin)",
                }
                break

    missing: list[str] = []
    if cr is not None:
        if not age:
            missing.append("age")
        if not sex:
            missing.append("sex")
        if acr is None:
            missing.append("urine albumin/creatinine ratio (UACR)")
        if baseline_cr is None:
            missing.append("last known (baseline) creatinine")

    prevent = compute_prevent_risk(ctx, values_by_lab, egfr)

    return {
        "results": results,
        "derived": {
            "bun_cr_ratio": bun_cr,
            "bun_cr_ratio_interpretation": interpret_bun_cr_ratio(bun_cr),
            "anion_gap": ag,
            "lft_r_factor": lft_r,
            "lft_pattern": lft_pattern,
            "lft_pattern_interpretation": interpret_lft_pattern(lft_pattern, lft_r),
            "anemia_pattern": anemia_pattern,
            "anemia_workup": interpret_anemia_workup(anemia_pattern, mcv),
            "egfr": egfr,
            "egfr_formula": "CKD-EPI 2021 (no race coefficient)",
            "ckd_g_stage": g_stage,
            "ckd_a_stage": a_stage,
            "ckd_ga_stage": ga_stage,
            "kdigo_aki_stage": aki_stage,
            "chronic_ckd_labs_indicated": chronic_ckd_labs_indicated(g_stage),
            "missing_for_ckd_staging": missing,
            "prevent": prevent,
        },
    }


URGENCY_BY_SEVERITY: dict[str, str] = {
    "Critical Low":  "Emergent — direct ED transport",
    "Critical High": "Emergent — direct ED transport",
    "Severe Low":    "Urgent — same-day evaluation; ED if symptomatic",
    "Severe High":   "Urgent — same-day evaluation; ED if symptomatic",
    "Moderate Low":  "Prompt — within 24–48 h",
    "Moderate High": "Prompt — within 24–48 h",
    "Mild Low":      "Routine — within 1–2 weeks",
    "Mild High":     "Routine — within 1–2 weeks",
    "Normal":        "No action required",
    "Unknown":       "Indeterminate — review thresholds",
}


SEVERITY_COLORS: dict[str, str] = {
    "Normal":        "#4caf50",
    "Mild Low":      "#90caf9",
    "Mild High":     "#90caf9",
    "Moderate Low":  "#ffb74d",
    "Moderate High": "#ffb74d",
    "Severe Low":    "#e57373",
    "Severe High":   "#e57373",
    "Critical Low":  "#b71c1c",
    "Critical High": "#b71c1c",
    "Unknown":       "#cfd8dc",
}
