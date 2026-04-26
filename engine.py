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


def evaluate(
    lab_id: str,
    value: float,
    rules: dict,
    context: dict | None = None,
) -> dict:
    """Evaluate a single lab value and return a structured result.

    Result keys: lab_id, display_name, value, unit, severity, follow_up,
    threshold_used_default, differentiation, thresholds, sources.
    On unknown lab_id returns {lab_id, value, error}.
    """
    lab_def = rules.get("labs", {}).get(lab_id)
    if not lab_def:
        return {"lab_id": lab_id, "value": value, "error": f"Unknown lab: {lab_id}"}

    thresholds, used_default = pick_thresholds(lab_def, context)
    severity = find_severity(value, thresholds)
    follow_up_def = lab_def.get("follow_up", {}).get(severity)

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
        "threshold_used_default": used_default,
        "differentiation": lab_def.get("differentiation"),
        "thresholds": thresholds,
        "sources": lab_def.get("sources", []),
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
