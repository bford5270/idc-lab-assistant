"""Engine for evaluating lab values against rules.json.

Pure module — no Streamlit imports. Testable independently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_rules(path: str | Path = "rules.json") -> dict:
    """Load the canonical rules JSON."""
    with open(path) as f:
        return json.load(f)


def pick_thresholds(lab_def: dict, context: dict | None) -> tuple[list[dict], bool]:
    """Pick the appropriate threshold list for the given patient context.

    Returns (thresholds_list, used_default_flag). used_default_flag is True
    when we fell back to the 'default' band set because sex (or other context
    key) was not provided or not recognized.
    """
    if "thresholds" in lab_def:
        return lab_def["thresholds"], False

    by_context = lab_def.get("thresholds_by_context", {})
    sex = (context or {}).get("sex")
    if sex and sex in by_context:
        return by_context[sex], False
    return by_context.get("default", []), True


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
) -> dict:
    """Evaluate a single lab value and return a structured result.

    Result keys: lab_id, display_name, value, unit, severity, follow_up,
    follow_up_branch, threshold_used_default, differentiation, thresholds,
    sources. On unknown lab_id returns {lab_id, value, error}.
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

    return {
        "lab_id": lab_id,
        "display_name": lab_def.get("display_name", lab_id),
        "value": value,
        "unit": lab_def.get("unit", ""),
        "severity": severity,
        "follow_up": rendered,
        "follow_up_branch": branch,
        "threshold_used_default": used_default,
        "differentiation": lab_def.get("differentiation"),
        "thresholds": thresholds,
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

    try:
        import pyprevent  # type: ignore[import-untyped]
    except ImportError:
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
    results = [evaluate(lab_id, value, rules, context) for lab_id, value in lab_inputs]
    values_by_lab = {
        r["lab_id"]: r["value"] for r in results if "lab_id" in r and "error" not in r
    }
    ctx = context or {}

    bun = values_by_lab.get("bun")
    cr = values_by_lab.get("creatinine")
    na = values_by_lab.get("sodium")
    cl = values_by_lab.get("chloride")
    hco3 = values_by_lab.get("bicarbonate")
    age = ctx.get("age")
    sex = ctx.get("sex")
    baseline_cr = ctx.get("baseline_creatinine")
    acr = ctx.get("urine_acr")

    egfr = compute_egfr(cr, age, sex) if cr is not None else None
    g_stage = assign_ckd_g_stage(egfr)
    a_stage = assign_ckd_a_stage(acr)
    ga_stage = (g_stage + a_stage) if (g_stage and a_stage) else None
    aki_stage = compute_kdigo_aki_stage(cr, baseline_cr) if cr is not None else None
    bun_cr = compute_bun_cr_ratio(bun, cr)
    ag = compute_anion_gap(na, cl, hco3)

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
