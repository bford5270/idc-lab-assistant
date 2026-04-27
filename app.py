"""Streamlit UI for the IDC Lab Assistant.

Loads rules.json via engine.load_rules, accepts manual or pasted lab
inputs, runs evaluate_panel for per-lab results plus session-derived
values (BUN/Cr ratio, anion gap, eGFR, CKD G_A_, KDIGO AKI stage), and
renders structured per-lab follow-up plus a combined session summary.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import streamlit as st

from engine import (
    SEVERITY_COLORS,
    URGENCY_BY_SEVERITY,
    evaluate_panel,
    load_rules,
)
from lab_parser import parse_text


st.set_page_config(page_title="IDC Lab Assistant", layout="wide")

st.warning(
    "**De-identified test data only.** This is a clinical decision support tool. "
    "Do not paste PHI/PII. Use clinical judgment — this tool does not replace it.",
    icon="⚠️",
)

st.title("IDC Lab Assistant")


@st.cache_data
def _load_rules_cached() -> dict:
    return load_rules("rules.json")


rules = _load_rules_cached()


# ---------- Sidebar ----------

with st.sidebar:
    st.header("Patient context (optional)")
    st.caption(
        "All fields optional. Sex sharpens Hgb / Cr / ALT / AST bands; "
        "diabetic status reframes glucose interpretation."
    )
    sex_choice = st.selectbox("Sex", options=["—", "female", "male"], index=0)
    age_input = st.number_input("Age", min_value=0, max_value=120, value=0, step=1)
    pregnancy = st.checkbox("Pregnant", value=False)
    diabetic_choice = st.selectbox("Diabetic?", options=["—", "no", "yes"], index=0)

    st.markdown("---")
    st.subheader("Kidney workup (optional)")
    st.caption(
        "If creatinine is being evaluated, these unlock KDIGO AKI staging "
        "and CKD G_A_ assignment."
    )
    baseline_cr = st.number_input(
        "Last known creatinine (mg/dL)",
        min_value=0.0, max_value=20.0, value=0.0, step=0.1, format="%.2f",
        help="Most recent prior creatinine. Engine uses for KDIGO AKI staging.",
    )
    baseline_cr_date = st.text_input(
        "Approximate date of last Cr",
        help="e.g. '6 months ago' or '2024-09-15' — for documentation only.",
    )
    urine_acr = st.number_input(
        "Urine albumin/Cr ratio (UACR, mg/g)",
        min_value=0.0, value=0.0, step=1.0,
        help="Order if not done; required to assign CKD A-stage.",
    )

    context: dict = {}
    if sex_choice != "—":
        context["sex"] = sex_choice
    if age_input > 0:
        context["age"] = age_input
    if pregnancy:
        context["pregnancy"] = True
    if diabetic_choice == "yes":
        context["diabetic"] = True
    elif diabetic_choice == "no":
        context["diabetic"] = False
    if baseline_cr > 0:
        context["baseline_creatinine"] = baseline_cr
    if baseline_cr_date.strip():
        context["baseline_creatinine_date"] = baseline_cr_date.strip()
    if urine_acr > 0:
        context["urine_acr"] = urine_acr


# ---------- Input modes ----------

tab_manual, tab_paste = st.tabs(["Manual entry", "Paste lab text"])
panel_result: dict | None = None

with tab_manual:
    cols = st.columns([2, 1])
    with cols[0]:
        lab_choices = sorted(rules["labs"].keys())
        lab_id = st.selectbox(
            "Lab",
            options=lab_choices,
            format_func=lambda lid: rules["labs"][lid]["display_name"],
        )
    with cols[1]:
        value = st.number_input(
            "Value", min_value=0.0, value=0.0, step=0.1, format="%.2f"
        )

    if st.button("Evaluate", key="manual_eval") and value > 0:
        panel_result = evaluate_panel([(lab_id, value)], rules, context)

with tab_paste:
    text_in = st.text_area(
        "Paste lab data (one lab per line, e.g. 'K 6.2'):",
        height=200,
    )
    if st.button("Evaluate", key="paste_eval") and text_in.strip():
        parsed = parse_text(text_in, rules)
        if not parsed:
            st.warning("No recognized labs found in input.")
        else:
            inputs = [(p.lab_id, p.value) for p in parsed]
            panel_result = evaluate_panel(inputs, rules, context)


# ---------- Rendering helpers ----------

SEVERITY_PRIORITY: dict[str, int] = {
    "Critical Low": 0, "Critical High": 0,
    "Severe Low": 1, "Severe High": 1,
    "Moderate Low": 2, "Moderate High": 2,
    "Mild Low": 3, "Mild High": 3,
    "Normal": 4, "Unknown": 5,
}


def _plot_lab_bar(result: dict) -> None:
    thresholds = result.get("thresholds", [])
    if not thresholds:
        return
    mins = [t.get("min") for t in thresholds if t.get("min") is not None]
    maxs = [t.get("max") for t in thresholds if t.get("max") is not None]
    plot_min = min(mins) if mins else 0.0
    plot_max = max(maxs) if maxs else (plot_min + 1.0)
    margin = max((plot_max - plot_min) * 0.1, 0.5)
    val = result["value"]
    if val < plot_min:
        plot_min = val - margin
    if val > plot_max:
        plot_max = val + margin

    fig, ax = plt.subplots(figsize=(8, 1.6))
    seen: set[str] = set()
    for t in thresholds:
        lo = t.get("min", plot_min)
        hi = t.get("max", plot_max)
        color = SEVERITY_COLORS.get(t["severity"], "#cfd8dc")
        label = t["severity"] if t["severity"] not in seen else None
        if label:
            seen.add(t["severity"])
        ax.barh(0, hi - lo, left=lo, height=0.4, color=color, edgecolor="white", label=label)
    ax.axvline(val, color="black", linestyle="-", linewidth=2)
    ax.set_yticks([])
    ax.set_xlim(plot_min, plot_max)
    ax.set_title(f"{result['display_name']}: {val} {result['unit']}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=4, fontsize=8)
    st.pyplot(fig)
    plt.close(fig)


def render_creatinine_differentiation(result: dict, derived: dict, diff: dict) -> None:
    st.markdown("#### AKI vs CKD assessment")

    egfr = derived.get("egfr")
    g_stage = derived.get("ckd_g_stage")
    ga_stage = derived.get("ckd_ga_stage")
    aki_stage = derived.get("kdigo_aki_stage")
    missing = derived.get("missing_for_ckd_staging", [])
    chronic_indicated = derived.get("chronic_ckd_labs_indicated", False)

    cols = st.columns(3)
    cols[0].metric("eGFR (CKD-EPI 2021)", f"{egfr}" if egfr else "—",
                   help="mL/min/1.73 m². Requires age + sex.")
    cols[1].metric("CKD G_A_ stage", ga_stage or g_stage or "—")
    cols[2].metric("KDIGO AKI stage", aki_stage or "—",
                   help="Requires last known creatinine.")

    if missing:
        st.warning(
            "Missing for full kidney staging: "
            + ", ".join(missing)
            + ". Document or order these to enable complete G_A_ assignment."
        )

    if chronic_indicated:
        st.error(f"**At {g_stage} — order chronic CKD lab panel:**")
        for lab_name in diff.get("chronic_lab_panel", []):
            st.markdown(f"- {lab_name}")

    with st.expander("Acute vs chronic feature reference"):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Acute pattern features:**")
            for f in diff.get("acute_pattern_features", []):
                st.markdown(f"- {f}")
        with cols[1]:
            st.markdown("**Chronic pattern features:**")
            for f in diff.get("chronic_pattern_features", []):
                st.markdown(f"- {f}")
        if diff.get("mixed_pattern_note"):
            st.info(diff["mixed_pattern_note"])
        implications = diff.get("workup_implications", {})
        if implications:
            st.markdown("**Workup implications by pattern:**")
            for pattern, plan in implications.items():
                st.markdown(f"- *{pattern.replace('_', ' ').title()}:* {plan}")


def render_result(result: dict, derived: dict) -> None:
    if "error" in result:
        st.error(result["error"])
        return

    severity = result["severity"]
    urgency = URGENCY_BY_SEVERITY.get(severity, "Indeterminate")

    st.markdown(f"### {result['display_name']}: {result['value']} {result['unit']}")
    st.markdown(f"**Severity:** {severity}  ·  **Urgency:** {urgency}")

    if result.get("threshold_used_default"):
        st.info(
            "Sex was not provided — used conservative default thresholds. "
            "Set sex in the sidebar for sharper bands."
        )

    branch = result.get("follow_up_branch")
    lab_def = rules["labs"].get(result["lab_id"], {})
    if branch == "diabetic":
        st.caption("Interpretation tailored for known diabetic.")
    elif branch == "default" and "follow_up_by_context" in lab_def:
        st.caption(
            "Interpretation for non-diabetic. Set 'Diabetic? Yes' in the "
            "sidebar if patient is a known diabetic."
        )

    follow_up = result.get("follow_up")
    if follow_up:
        if follow_up.get("category"):
            st.markdown(f"**Category:** {follow_up['category']}")
        if follow_up.get("next_tests"):
            st.markdown("**Next tests / workup:**")
            for t in follow_up["next_tests"]:
                st.markdown(f"- {t}")
        if follow_up.get("ehr_plan"):
            st.markdown("**EHR plan (paste-ready):**")
            st.code(follow_up["ehr_plan"], language="markdown")
        if follow_up.get("patient_communication"):
            st.markdown("**Patient communication (paste-ready):**")
            st.code(follow_up["patient_communication"], language="markdown")
    elif severity == "Normal":
        st.success("No action required.")

    differentiation = result.get("differentiation")
    if differentiation and result["lab_id"] == "creatinine":
        render_creatinine_differentiation(result, derived, differentiation)

    if result["lab_id"] in ("creatinine", "bun") and derived.get("bun_cr_ratio_interpretation"):
        st.info(derived["bun_cr_ratio_interpretation"])

    _plot_lab_bar(result)

    if result.get("sources"):
        with st.expander("Sources"):
            st.markdown(", ".join(result["sources"]))

    st.markdown("---")


def render_session_derived(derived: dict) -> None:
    has_anything = any(
        derived.get(k) is not None
        for k in ("bun_cr_ratio", "anion_gap", "egfr", "kdigo_aki_stage")
    )
    if not has_anything:
        return

    st.markdown("## Session-derived values")
    cols = st.columns(2)
    if derived.get("bun_cr_ratio") is not None:
        cols[0].metric("BUN/Cr ratio", str(derived["bun_cr_ratio"]))
    if derived.get("anion_gap") is not None:
        cols[1].metric("Anion gap", str(derived["anion_gap"]),
                       help="Normal 8–12. Computed when Na, Cl, HCO3 all present.")

    if derived.get("egfr") is not None:
        st.markdown(
            f"**eGFR (CKD-EPI 2021):** {derived['egfr']} mL/min/1.73 m²  ·  "
            f"**G stage:** {derived.get('ckd_g_stage') or '—'}  ·  "
            f"**A stage:** {derived.get('ckd_a_stage') or '—'}  ·  "
            f"**G_A_:** {derived.get('ckd_ga_stage') or '—'}"
        )
    if derived.get("kdigo_aki_stage"):
        st.markdown(f"**KDIGO AKI staging:** {derived['kdigo_aki_stage']}")
    if derived.get("bun_cr_ratio_interpretation"):
        st.info(derived["bun_cr_ratio_interpretation"])

    st.markdown("---")


def render_combined_session_output(results: list[dict], derived: dict) -> None:
    valid = [r for r in results if "error" not in r and r.get("follow_up")]
    if not valid:
        return

    sorted_results = sorted(
        valid, key=lambda r: SEVERITY_PRIORITY.get(r["severity"], 99)
    )

    seen: set[str] = set()
    combined_orders: list[str] = []
    for r in sorted_results:
        for t in r["follow_up"].get("next_tests", []):
            if t not in seen:
                seen.add(t)
                combined_orders.append(t)

    derived_lines: list[str] = []
    if derived.get("bun_cr_ratio_interpretation"):
        derived_lines.append(derived["bun_cr_ratio_interpretation"])
    if derived.get("anion_gap") is not None:
        derived_lines.append(f"Anion gap = {derived['anion_gap']} (normal 8–12).")
    if derived.get("egfr") is not None:
        ga = derived.get("ckd_ga_stage") or derived.get("ckd_g_stage") or "incomplete data"
        derived_lines.append(
            f"eGFR {derived['egfr']} mL/min/1.73 m² (CKD-EPI 2021); CKD stage: {ga}."
        )
    if derived.get("kdigo_aki_stage"):
        derived_lines.append(f"KDIGO AKI staging: {derived['kdigo_aki_stage']}.")
    if derived.get("missing_for_ckd_staging"):
        derived_lines.append(
            "Missing for complete CKD staging: "
            + ", ".join(derived["missing_for_ckd_staging"])
            + "."
        )

    ap_lines: list[str] = []
    if derived_lines:
        ap_lines.append("# Derived values")
        ap_lines.extend(derived_lines)
        ap_lines.append("")
    for r in sorted_results:
        ap_lines.append(f"# {r['display_name']} ({r['severity']})")
        plan = r["follow_up"].get("ehr_plan", "")
        if plan:
            ap_lines.append(plan)
        ap_lines.append("")

    pt_lines: list[str] = []
    for r in sorted_results:
        pt_lines.append(f"# {r['display_name']}")
        comm = r["follow_up"].get("patient_communication", "")
        if comm:
            pt_lines.append(comm)
        pt_lines.append("")

    st.markdown("## Session summary (paste-ready)")
    st.caption("Severity-ordered, deduped. Each tab is a single block ready to copy.")
    tabs = st.tabs(["Combined order list", "Clinical A/P", "Patient summary"])
    with tabs[0]:
        st.code("\n".join(f"- {o}" for o in combined_orders) or "(no orders)", language="markdown")
    with tabs[1]:
        st.code("\n".join(ap_lines).strip() or "(no plan)", language="markdown")
    with tabs[2]:
        st.code("\n".join(pt_lines).strip() or "(no patient communication)", language="markdown")


# ---------- Top-level rendering ----------

if panel_result:
    derived = panel_result["derived"]
    results = panel_result["results"]

    render_session_derived(derived)
    for r in results:
        render_result(r, derived)
    render_combined_session_output(results, derived)
