"""Vision-based lab extraction from screenshots.

Pure module — no Streamlit imports. Calls the Anthropic API with a
screenshot (e.g. a Genesis lab table) and returns structured lab values
constrained to the lab_id allowlist defined in rules.json.

The returned ExtractedLab tuples are shaped for the same downstream
flow as lab_parser.parse_text — callers can hand them directly to
engine.evaluate_panel after IDC review/correction.
"""

from __future__ import annotations

import base64
import json
import os
from typing import NamedTuple

import anthropic


DEFAULT_MODEL = "claude-haiku-4-5"


class ExtractedLab(NamedTuple):
    lab_id: str
    value: float
    raw_label: str


class LabScreenshotError(RuntimeError):
    """Raised when extraction fails for a reason the UI should surface."""


def resolve_api_key(sidebar_key: str | None = None) -> str | None:
    """Return the Anthropic API key from sidebar input or env var.

    Sidebar input wins when provided (lets an IDC paste their own key on
    a shared/hosted deployment). Falls back to ANTHROPIC_API_KEY in the
    environment for local-run setups.
    """
    if sidebar_key and sidebar_key.strip():
        return sidebar_key.strip()
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return env_key or None


def _build_allowlist(rules: dict) -> str:
    lines = []
    for lab_id, lab_def in sorted(rules["labs"].items()):
        display = lab_def.get("display_name", lab_id)
        synonyms = ", ".join(lab_def.get("synonyms", [])[:6])
        lines.append(f"- {lab_id} ({display}): {synonyms}")
    return "\n".join(lines)


def _build_schema(rules: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "labs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "lab_id": {
                            "type": "string",
                            "enum": sorted(rules["labs"].keys()),
                        },
                        "value": {"type": "number"},
                        "raw_label": {"type": "string"},
                    },
                    "required": ["lab_id", "value", "raw_label"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["labs"],
        "additionalProperties": False,
    }


def _build_system_prompt(rules: dict) -> str:
    return (
        "You extract structured lab values from clinical lab table "
        "screenshots. Return only labs whose lab_id appears on the "
        "allowlist below.\n\n"
        f"Allowlist (lab_id — display name: synonyms):\n{_build_allowlist(rules)}\n\n"
        "Rules:\n"
        "1. Only return labs whose lab_id is on the allowlist. Skip everything else.\n"
        "2. If a lab appears with multiple result columns (today vs prior), "
        "take the most recent / leftmost numeric column.\n"
        "3. The 'value' is the numeric result only — strip units, reference "
        "ranges, and abnormal flags (H, L, *, !).\n"
        "4. The 'raw_label' is the lab name as it appeared in the screenshot.\n"
        "5. If you cannot read a value with confidence, omit that lab "
        "rather than guessing.\n"
        "6. Return numbers as numeric values (4.2, not \"4.2\")."
    )


def extract_labs_from_image(
    image_bytes: bytes,
    rules: dict,
    *,
    media_type: str = "image/png",
    client: anthropic.Anthropic | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> list[ExtractedLab]:
    """Extract lab values from a screenshot using Claude vision.

    Constrains the model output to lab_ids defined in rules.json via
    json_schema structured outputs. Filters anything that slips through
    the schema (defensive — schema enforcement is reliable but not free).

    Raises LabScreenshotError on missing API key. Anthropic SDK errors
    propagate as-is so the UI can render typed messages.
    """
    if client is None:
        key = api_key or resolve_api_key()
        if not key:
            raise LabScreenshotError(
                "No Anthropic API key. Set ANTHROPIC_API_KEY or paste a key "
                "in the sidebar."
            )
        client = anthropic.Anthropic(api_key=key)

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_build_system_prompt(rules),
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _build_schema(rules),
            }
        },
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract the lab values from this screenshot.",
                    },
                ],
            }
        ],
    )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    allowed_ids = set(rules["labs"].keys())
    results: list[ExtractedLab] = []
    for item in data.get("labs", []):
        lab_id = item.get("lab_id")
        if lab_id not in allowed_ids:
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        results.append(
            ExtractedLab(
                lab_id=lab_id,
                value=value,
                raw_label=str(item.get("raw_label", "")),
            )
        )

    return results
