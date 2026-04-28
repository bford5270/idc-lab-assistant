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
    evaluate_serology,
    load_rules,
)
from lab_parser import parse_text
from lab_screenshot import (
    LabScreenshotError,
    extract_labs_from_image,
    resolve_api_key,
)


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
    trimester_choice = st.selectbox(
        "Trimester (if pregnant)",
        options=["—", "1", "2", "3"], index=0,
        help="Selects trimester-specific TSH bands per ATA 2017. "
             "Leave blank for the generic pregnancy band.",
    )
    diabetic_choice = st.selectbox("Diabetic?", options=["—", "no", "yes"], index=0)
    tb_risk_choice = st.selectbox(
        "TB risk category (for PPD interpretation)",
        options=["—", "low", "moderate", "high"], index=0,
        help="High: HIV+, recent contact, immunosuppressed. Moderate: "
             "high-prevalence-country immigrants <5y, IV drug users, "
             "congregate settings, lab workers, diabetes / CKD / silicosis "
             "/ certain cancers. Low: no risk factors.",
    )

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

    st.markdown("---")
    st.subheader("Cardiovascular risk inputs (PREVENT)")
    st.caption(
        "If you evaluate total cholesterol + HDL alongside these inputs, "
        "the AHA PREVENT 2023 10-year ASCVD / CVD / HF risk is computed "
        "automatically. Validated for ages 30–79 without prior CVD."
    )
    systolic_bp = st.number_input(
        "Systolic BP (mmHg)",
        min_value=0, max_value=250, value=0, step=1,
        help="PREVENT requires SBP 90–200.",
    )
    smoker_choice = st.selectbox("Current smoker?", options=["—", "no", "yes"], index=0)
    bmi = st.number_input(
        "BMI (kg/m²)",
        min_value=0.0, max_value=80.0, value=0.0, step=0.1, format="%.1f",
        help="PREVENT requires BMI 18.5–39.9.",
    )
    on_htn_meds_choice = st.selectbox("On antihypertensive medication?", options=["—", "no", "yes"], index=0)
    on_statin_choice = st.selectbox("On lipid-lowering / statin therapy?", options=["—", "no", "yes"], index=0)

    st.markdown("---")
    st.subheader("Screenshot upload (optional)")
    st.caption(
        "Required only for the Upload screenshot tab. Used once per upload "
        "to call Claude vision and parse the lab table. ANTHROPIC_API_KEY "
        "in the environment is used automatically; this field overrides it."
    )
    sidebar_api_key = st.text_input(
        "Anthropic API key", type="password",
        help="Leave blank to use the ANTHROPIC_API_KEY env var.",
    )

    context: dict = {}
    if sex_choice != "—":
        context["sex"] = sex_choice
    if age_input > 0:
        context["age"] = age_input
    if pregnancy:
        context["pregnancy"] = True
        if trimester_choice in ("1", "2", "3"):
            context["trimester"] = int(trimester_choice)
    if diabetic_choice == "yes":
        context["diabetic"] = True
    elif diabetic_choice == "no":
        context["diabetic"] = False
    if tb_risk_choice in ("low", "moderate", "high"):
        context["tb_risk_category"] = tb_risk_choice
    if baseline_cr > 0:
        context["baseline_creatinine"] = baseline_cr
    if baseline_cr_date.strip():
        context["baseline_creatinine_date"] = baseline_cr_date.strip()
    if urine_acr > 0:
        context["urine_acr"] = urine_acr
    if systolic_bp > 0:
        context["systolic_bp"] = systolic_bp
    if smoker_choice in ("yes", "no"):
        context["current_smoker"] = (smoker_choice == "yes")
    if bmi > 0:
        context["bmi"] = bmi
    if on_htn_meds_choice in ("yes", "no"):
        context["on_htn_meds"] = (on_htn_meds_choice == "yes")
    if on_statin_choice in ("yes", "no"):
        context["on_cholesterol_meds"] = (on_statin_choice == "yes")


# ---------- Input modes ----------

tab_manual, tab_paste, tab_shot, tab_sero = st.tabs(
    ["Manual entry", "Paste lab text", "Upload screenshot", "Serology"]
)
panel_result: dict | None = None
serology_result: dict | None = None

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

with tab_shot:
    st.caption(
        "Upload a screenshot of a lab table (e.g. from Genesis). The image is "
        "sent to Claude vision once for parsing — **de-identified data only**, "
        "same policy as the rest of the tool. Review and correct values before "
        "evaluating."
    )
    uploaded = st.file_uploader(
        "Lab-table screenshot",
        type=["png", "jpg", "jpeg"],
        key="shot_uploader",
    )

    if uploaded is not None:
        st.image(uploaded, caption=uploaded.name, use_container_width=True)

        if st.button("Extract labs from screenshot", key="shot_extract"):
            api_key = resolve_api_key(sidebar_api_key)
            if not api_key:
                st.error(
                    "No Anthropic API key. Paste one in the sidebar or set "
                    "ANTHROPIC_API_KEY in the environment."
                )
            else:
                with st.spinner("Calling Claude vision…"):
                    try:
                        extracted = extract_labs_from_image(
                            uploaded.getvalue(),
                            rules,
                            media_type=uploaded.type or "image/png",
                            api_key=api_key,
                        )
                    except LabScreenshotError as exc:
                        st.error(str(exc))
                        extracted = []
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Vision call failed: {exc}")
                        extracted = []
                st.session_state["shot_extracted"] = [
                    {"lab_id": e.lab_id, "value": e.value, "raw_label": e.raw_label}
                    for e in extracted
                ]
                if extracted:
                    st.success(f"Extracted {len(extracted)} labs. Review below.")
                else:
                    st.warning("No recognized labs were extracted.")

    rows = st.session_state.get("shot_extracted", [])
    if rows:
        st.markdown("**Review extracted values** — fix any OCR errors before evaluating.")
        edited = st.data_editor(
            rows,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "lab_id": st.column_config.SelectboxColumn(
                    "Lab", options=sorted(rules["labs"].keys()), required=True,
                ),
                "value": st.column_config.NumberColumn(
                    "Value", required=True, format="%.2f",
                ),
                "raw_label": st.column_config.TextColumn(
                    "Source label", help="As read from the screenshot — informational only.",
                ),
            },
            key="shot_editor",
        )
        if st.button("Use these values", key="shot_eval"):
            inputs = [
                (r["lab_id"], float(r["value"]))
                for r in edited
                if r.get("lab_id") and r.get("value") is not None
            ]
            if inputs:
                panel_result = evaluate_panel(inputs, rules, context)
            else:
                st.warning("Add at least one lab + value before evaluating.")


_SEROLOGY_LABS = {
    lab_id: lab_def
    for lab_id, lab_def in rules["labs"].items()
    if lab_def.get("kind") == "serology"
}


def _to_bool(state: str) -> bool | None:
    if state == "Positive":
        return True
    if state == "Negative":
        return False
    return None


with tab_sero:
    if not _SEROLOGY_LABS:
        st.info("No serology panels configured.")
    else:
        sero_lab_id = st.selectbox(
            "Serology panel",
            options=sorted(_SEROLOGY_LABS.keys()),
            format_func=lambda lid: _SEROLOGY_LABS[lid]["display_name"],
            key="sero_lab",
        )
        sero_def = _SEROLOGY_LABS[sero_lab_id]
        st.caption(
            "Set each marker to Positive, Negative, or leave at — for "
            "Not done. The engine matches the most specific named pattern; "
            "missing markers are surfaced in the result."
        )

        sero_inputs: dict = {}
        cols = st.columns(min(len(sero_def["inputs"]), 4))
        for i, marker in enumerate(sero_def["inputs"]):
            choice = cols[i % len(cols)].selectbox(
                marker["label"],
                options=["—", "Positive", "Negative"],
                index=0,
                key=f"sero_{sero_lab_id}_{marker['id']}",
            )
            sero_inputs[marker["id"]] = _to_bool(choice)

        if st.button("Interpret", key="sero_eval"):
            serology_result = evaluate_serology(sero_lab_id, sero_inputs, rules)


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

    if result.get("pregnancy_thresholds"):
        st.info(
            "Pregnancy-specific thresholds applied. Set trimester in the "
            "sidebar for trimester-tuned TSH bands per ATA 2017."
        )

    if result.get("elderly_thresholds"):
        st.info(
            "Age-adjusted thresholds applied (≥70). TSH upper limit widens "
            "to 5.0 mIU/L per ATA hypothyroidism guidance on age-related rise."
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

    correction = result.get("correction")
    if correction and correction.get("type") == "albumin_corrected":
        corr_severity = correction["severity"]
        corr_urgency = URGENCY_BY_SEVERITY.get(corr_severity, "Indeterminate")
        shifted = corr_severity != severity
        message = (
            f"**Albumin-corrected Ca:** {correction['value']} mg/dL  ·  "
            f"**Severity:** {corr_severity}  ·  **Urgency:** {corr_urgency}  \n"
            f"Albumin = {correction['albumin']} g/dL. "
            f"Formula: {correction['formula']}."
        )
        (st.warning if shifted else st.info)(message)
        if shifted and correction.get("follow_up"):
            with st.expander(
                f"Follow-up for corrected Ca ({corr_severity})", expanded=False
            ):
                fu = correction["follow_up"]
                if fu.get("category"):
                    st.markdown(f"**Category:** {fu['category']}")
                if fu.get("next_tests"):
                    st.markdown("**Next tests / workup:**")
                    for t in fu["next_tests"]:
                        st.markdown(f"- {t}")
                if fu.get("ehr_plan"):
                    st.markdown("**EHR plan (paste-ready):**")
                    st.code(fu["ehr_plan"], language="markdown")
                if fu.get("patient_communication"):
                    st.markdown("**Patient communication (paste-ready):**")
                    st.code(fu["patient_communication"], language="markdown")

    differentiation = result.get("differentiation")
    if differentiation and result["lab_id"] == "creatinine":
        render_creatinine_differentiation(result, derived, differentiation)

    if result["lab_id"] in ("creatinine", "bun") and derived.get("bun_cr_ratio_interpretation"):
        st.info(derived["bun_cr_ratio_interpretation"])

    if (
        result["lab_id"] in ("alt", "ast", "alkaline_phosphatase")
        and derived.get("lft_pattern_interpretation")
    ):
        st.info(derived["lft_pattern_interpretation"])

    if (
        result["lab_id"] in ("hemoglobin", "mcv")
        and derived.get("anemia_workup")
    ):
        st.info(derived["anemia_workup"])

    _plot_lab_bar(result)

    if result.get("sources"):
        with st.expander("Sources"):
            st.markdown(", ".join(result["sources"]))

    st.markdown("---")


def render_session_derived(derived: dict) -> None:
    prevent = derived.get("prevent") or {}
    has_anything = (
        derived.get("bun_cr_ratio") is not None
        or derived.get("anion_gap") is not None
        or derived.get("lft_r_factor") is not None
        or derived.get("anemia_pattern")
        or derived.get("egfr") is not None
        or derived.get("kdigo_aki_stage")
        or prevent.get("available")
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

    if derived.get("lft_r_factor") is not None:
        pattern = derived.get("lft_pattern") or "—"
        st.markdown(
            f"**LFT pattern (R-factor):** R = {derived['lft_r_factor']}  ·  "
            f"**Pattern:** {pattern.title()}"
        )
        if derived.get("lft_pattern_interpretation"):
            st.info(derived["lft_pattern_interpretation"])

    if derived.get("anemia_pattern"):
        st.markdown(
            f"**Anemia pattern (MCV-based):** {derived['anemia_pattern'].title()}"
        )
        if derived.get("anemia_workup"):
            st.info(derived["anemia_workup"])

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

    if prevent.get("available"):
        st.markdown("### AHA PREVENT 2023 — 10-year risk")
        cols = st.columns(3)
        cols[0].metric("ASCVD", f"{prevent['ascvd_10y']}%")
        cols[1].metric("Total CVD", f"{prevent['cvd_10y']}%")
        cols[2].metric("Heart failure", f"{prevent['hf_10y']}%")
        tier = prevent.get("risk_tier", "")
        tier_color = {"low": "🟢", "intermediate": "🟡", "high": "🔴"}.get(tier, "")
        st.markdown(f"**Risk tier:** {tier_color} {tier.title() if tier else '—'}")
        if prevent.get("statin_recommendation"):
            st.info(prevent["statin_recommendation"])
    elif prevent.get("missing"):
        st.caption(
            "PREVENT 10-yr risk not yet computed — missing: "
            + ", ".join(prevent["missing"])
            + ". Fill in the sidebar 'Cardiovascular risk inputs' section "
            "(and evaluate total cholesterol + HDL as labs) to enable it."
        )
    elif prevent.get("out_of_range"):
        st.warning("PREVENT not computed: " + "; ".join(prevent["out_of_range"]))

    st.markdown("---")


def _build_derived_lines(derived: dict) -> list[str]:
    """Produce the bulleted lines that go into the Derived Values block of the note."""
    lines: list[str] = []
    if derived.get("bun_cr_ratio_interpretation"):
        lines.append(derived["bun_cr_ratio_interpretation"])
    if derived.get("anion_gap") is not None:
        lines.append(f"Anion gap = {derived['anion_gap']} (normal 8–12).")
    if derived.get("lft_pattern") and derived.get("lft_r_factor") is not None:
        lines.append(
            f"LFT R-factor = {derived['lft_r_factor']} → "
            f"{derived['lft_pattern']} pattern."
        )
    if derived.get("anemia_pattern"):
        lines.append(f"Anemia pattern (MCV-based): {derived['anemia_pattern']}.")
    if derived.get("egfr") is not None:
        ga = derived.get("ckd_ga_stage") or derived.get("ckd_g_stage") or "incomplete data"
        lines.append(
            f"eGFR {derived['egfr']} mL/min/1.73 m² (CKD-EPI 2021); CKD stage: {ga}."
        )
    if derived.get("kdigo_aki_stage"):
        lines.append(f"KDIGO AKI staging: {derived['kdigo_aki_stage']}.")
    return lines


def render_combined_session_output(results: list[dict], derived: dict) -> None:
    valid = [r for r in results if "error" not in r]
    if not valid:
        return

    sorted_results = sorted(
        valid, key=lambda r: SEVERITY_PRIORITY.get(r["severity"], 99)
    )
    abnormal = [r for r in sorted_results if r["severity"] != "Normal" and r.get("follow_up")]
    normal = [r for r in sorted_results if r["severity"] == "Normal"]

    # ---- Action items: deduped next_tests + missing-data prompts ----
    seen_orders: set[str] = set()
    action_items: list[str] = []
    for r in abnormal:
        for t in r["follow_up"].get("next_tests", []):
            if t not in seen_orders:
                seen_orders.add(t)
                action_items.append(t)
    if derived.get("missing_for_ckd_staging"):
        action_items.append(
            "Document or order to enable complete CKD staging: "
            + ", ".join(derived["missing_for_ckd_staging"]) + "."
        )
    prevent = derived.get("prevent") or {}
    if prevent.get("missing"):
        action_items.append(
            "PREVENT 10-yr risk not yet computable — obtain: "
            + ", ".join(prevent["missing"]) + "."
        )

    # ---- Clinical note ----
    note_lines: list[str] = ["# Lab Review", ""]
    note_lines.append("**Values reviewed:** " + "; ".join(
        f"{r['display_name']} {r['value']} {r['unit']} ({r['severity']})"
        for r in sorted_results
    ))
    note_lines.append("")

    derived_lines = _build_derived_lines(derived)
    if derived_lines:
        note_lines.append("## Derived values")
        for line in derived_lines:
            note_lines.append(f"- {line}")
        note_lines.append("")

    if prevent.get("available"):
        note_lines.append("## AHA PREVENT 2023 — 10-year risk")
        note_lines.append(
            f"- ASCVD {prevent['ascvd_10y']}%, total CVD {prevent['cvd_10y']}%, "
            f"HF {prevent['hf_10y']}% — **{prevent['risk_tier']}** tier."
        )
        if prevent.get("statin_recommendation"):
            note_lines.append(f"- {prevent['statin_recommendation']}")
        note_lines.append("")

    if abnormal:
        note_lines.append("## Assessment & Plan")
        note_lines.append("")
        for r in abnormal:
            note_lines.append(f"### {r['display_name']} — {r['severity']}")
            plan = r["follow_up"].get("ehr_plan", "")
            if plan:
                note_lines.append(plan)
            note_lines.append("")
    else:
        note_lines.append("## Assessment")
        note_lines.append("All evaluated labs within normal range. No active issues identified from this panel.")
        note_lines.append("")

    if normal and abnormal:
        normal_names = ", ".join(r["display_name"] for r in normal)
        note_lines.append(f"**Normal:** {normal_names}.")

    # ---- Patient communication ----
    pt_lines: list[str] = ["# Your lab results", ""]
    if not abnormal:
        pt_lines.append("All of the labs we checked are within the normal range. No follow-up needed for these results at this time.")
    else:
        pt_lines.append("Here is a summary of your recent labs and what we will do next.")
        pt_lines.append("")
        for r in abnormal:
            pt_lines.append(f"## {r['display_name']}")
            comm = r["follow_up"].get("patient_communication", "")
            if comm:
                pt_lines.append(comm)
            pt_lines.append("")
        if normal:
            normal_names = ", ".join(r["display_name"] for r in normal)
            pt_lines.append(f"**Other labs that were normal:** {normal_names}.")

    # ---- Render: three stacked, always-visible sections ----
    st.markdown("## Session summary (paste-ready)")
    st.caption(
        "Three stacked blocks — copy any section using the icon at the top "
        "right corner of each block."
    )

    st.markdown("### 1. Action items / orders")
    if action_items:
        st.code("\n".join(f"- {item}" for item in action_items), language="markdown")
    else:
        st.success("No action items — all labs within normal range.")

    st.markdown("### 2. Clinical note")
    st.code("\n".join(note_lines).strip(), language="markdown")

    st.markdown("### 3. Patient communication")
    st.code("\n".join(pt_lines).strip(), language="markdown")


def render_serology_result(result: dict) -> None:
    if "error" in result:
        st.error(result["error"])
        return

    st.markdown(f"### {result['display_name']}: {result['pattern_label']}")

    if result.get("missing_inputs"):
        st.warning(
            "Marker(s) not done: "
            + ", ".join(result["missing_inputs"])
            + ". Pattern is the best match given the available markers — "
            "fill in the missing markers for a definitive interpretation."
        )

    if result.get("category"):
        st.markdown(f"**Category:** {result['category']}")

    if result.get("next_tests"):
        st.markdown("**Next tests / workup:**")
        for t in result["next_tests"]:
            st.markdown(f"- {t}")

    if result.get("ehr_plan"):
        st.markdown("**EHR plan (paste-ready):**")
        st.code(result["ehr_plan"], language="markdown")

    if result.get("patient_communication"):
        st.markdown("**Patient communication (paste-ready):**")
        st.code(result["patient_communication"], language="markdown")

    if result.get("sources"):
        with st.expander("Sources"):
            st.markdown(", ".join(result["sources"]))

    st.markdown("---")


# ---------- Top-level rendering ----------

if panel_result:
    derived = panel_result["derived"]
    results = panel_result["results"]

    render_session_derived(derived)
    for r in results:
        render_result(r, derived)
    render_combined_session_output(results, derived)

if serology_result:
    render_serology_result(serology_result)
