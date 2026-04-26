"""Streamlit UI for the IDC Lab Assistant.

Loads rules.json via engine.load_rules, accepts manual or pasted lab
inputs, and renders the structured follow-up output (category, next tests,
EHR plan, patient communication).
"""

from __future__ import annotations

import re

import matplotlib.pyplot as plt
import streamlit as st

from engine import (
    SEVERITY_COLORS,
    URGENCY_BY_SEVERITY,
    evaluate,
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


with st.sidebar:
    st.header("Patient context (optional)")
    st.caption(
        "All fields optional. If sex is not provided, sex-stratified labs "
        "(Hgb, Cr, ALT, AST) fall back to a conservative default."
    )
    sex_choice = st.selectbox("Sex", options=["—", "female", "male"], index=0)
    age_input = st.number_input("Age", min_value=0, max_value=120, value=0, step=1)
    pregnancy = st.checkbox("Pregnant", value=False)

    context: dict = {}
    if sex_choice != "—":
        context["sex"] = sex_choice
    if age_input > 0:
        context["age"] = age_input
    if pregnancy:
        context["pregnancy"] = True


tab_manual, tab_paste = st.tabs(["Manual entry", "Paste lab text"])

results: list[dict] = []

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
        value = st.number_input("Value", min_value=0.0, value=0.0, step=0.1, format="%.2f")

    if st.button("Evaluate", key="manual_eval") and value > 0:
        results = [evaluate(lab_id, value, rules, context)]

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
            results = [evaluate(p.lab_id, p.value, rules, context) for p in parsed]


def _plot_lab_bar(result: dict) -> None:
    """Plot non-overlapping severity zones with the value as a vertical line."""
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
    seen_labels: set[str] = set()
    for t in thresholds:
        lo = t.get("min", plot_min)
        hi = t.get("max", plot_max)
        color = SEVERITY_COLORS.get(t["severity"], "#cfd8dc")
        label = t["severity"] if t["severity"] not in seen_labels else None
        if label:
            seen_labels.add(t["severity"])
        ax.barh(0, hi - lo, left=lo, height=0.4, color=color, edgecolor="white", label=label)

    ax.axvline(val, color="black", linestyle="-", linewidth=2)
    ax.set_yticks([])
    ax.set_xlim(plot_min, plot_max)
    ax.set_title(f"{result['display_name']}: {val} {result['unit']}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=4, fontsize=8)
    st.pyplot(fig)
    plt.close(fig)


def _safe_key(s: str) -> str:
    return re.sub(r"\W+", "_", s)[:60]


def render_result(result: dict) -> None:
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
    if differentiation:
        is_abnormal = severity not in ("Normal", "Unknown")
        with st.expander(
            f"Clinical reasoning prompts — {differentiation.get('purpose', '')[:80]}",
            expanded=is_abnormal,
        ):
            st.caption("Step through the prompts to refine acute-vs-chronic reasoning.")
            for i, prompt in enumerate(differentiation.get("reasoning_prompts", [])):
                st.checkbox(prompt, key=f"{result['lab_id']}_diff_{i}_{_safe_key(prompt)}")

            st.markdown("---")
            cols = st.columns(2)
            with cols[0]:
                st.markdown("**Acute pattern features:**")
                for f in differentiation.get("acute_pattern_features", []):
                    st.markdown(f"- {f}")
            with cols[1]:
                st.markdown("**Chronic pattern features:**")
                for f in differentiation.get("chronic_pattern_features", []):
                    st.markdown(f"- {f}")
            mixed = differentiation.get("mixed_pattern_note")
            if mixed:
                st.info(mixed)
            implications = differentiation.get("workup_implications", {})
            if implications:
                st.markdown("**Workup implications by pattern:**")
                for pattern, plan in implications.items():
                    st.markdown(f"- *{pattern.replace('_', ' ').title()}:* {plan}")

    _plot_lab_bar(result)

    if result.get("sources"):
        with st.expander("Sources"):
            st.markdown(", ".join(result["sources"]))

    st.markdown("---")


for r in results:
    render_result(r)
