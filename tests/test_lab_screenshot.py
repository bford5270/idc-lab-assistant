"""Tests for lab_screenshot.py.

Mocks the Anthropic client — the module is purely a request builder
plus a JSON-response unpacker, so a fake client with the expected
response shape exercises the full data path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import load_rules
from lab_screenshot import (
    LabScreenshotError,
    _build_allowlist,
    _build_schema,
    extract_labs_from_image,
    resolve_api_key,
)


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


def _fake_client(response_text: str) -> object:
    """Build a stand-in for anthropic.Anthropic with messages.create()."""
    block = SimpleNamespace(type="text", text=response_text)
    response = SimpleNamespace(content=[block])

    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.captured = captured  # type: ignore[attr-defined]
    return client


# ---------- resolve_api_key ----------


def test_resolve_api_key_prefers_sidebar(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert resolve_api_key("sidebar-key") == "sidebar-key"


def test_resolve_api_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert resolve_api_key("") == "env-key"
    assert resolve_api_key(None) == "env-key"


def test_resolve_api_key_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert resolve_api_key(None) is None
    assert resolve_api_key("   ") is None


# ---------- _build_schema / _build_allowlist ----------


def test_schema_enum_matches_rules_keys(rules):
    schema = _build_schema(rules)
    enum = schema["properties"]["labs"]["items"]["properties"]["lab_id"]["enum"]
    assert set(enum) == set(rules["labs"].keys())


def test_schema_has_strict_additional_properties(rules):
    schema = _build_schema(rules)
    item = schema["properties"]["labs"]["items"]
    assert schema["additionalProperties"] is False
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"lab_id", "value", "raw_label"}


def test_allowlist_includes_each_lab(rules):
    allowlist = _build_allowlist(rules)
    for lab_id in rules["labs"]:
        assert lab_id in allowlist


# ---------- extract_labs_from_image ----------


def test_extract_happy_path(rules):
    payload = {
        "labs": [
            {"lab_id": "potassium", "value": 5.4, "raw_label": "K"},
            {"lab_id": "sodium", "value": 138, "raw_label": "Na"},
            {"lab_id": "glucose", "value": 142.5, "raw_label": "GLU"},
        ]
    }
    client = _fake_client(json.dumps(payload))
    extracted = extract_labs_from_image(b"fake-png-bytes", rules, client=client)

    assert [(e.lab_id, e.value) for e in extracted] == [
        ("potassium", 5.4),
        ("sodium", 138.0),
        ("glucose", 142.5),
    ]
    assert all(isinstance(e.value, float) for e in extracted)


def test_extract_filters_out_non_allowlisted_lab_ids(rules):
    """Defensive — schema enum should already reject these, but the
    post-parse filter is the second line of defense."""
    payload = {
        "labs": [
            {"lab_id": "potassium", "value": 4.0, "raw_label": "K"},
            {"lab_id": "ionized_calcium", "value": 1.2, "raw_label": "iCa"},
        ]
    }
    client = _fake_client(json.dumps(payload))
    extracted = extract_labs_from_image(b"fake", rules, client=client)
    assert [e.lab_id for e in extracted] == ["potassium"]


def test_extract_drops_non_numeric_values(rules):
    payload = {
        "labs": [
            {"lab_id": "potassium", "value": "not-a-number", "raw_label": "K"},
            {"lab_id": "sodium", "value": 140, "raw_label": "Na"},
        ]
    }
    client = _fake_client(json.dumps(payload))
    extracted = extract_labs_from_image(b"fake", rules, client=client)
    assert [e.lab_id for e in extracted] == ["sodium"]


def test_extract_handles_empty_response(rules):
    client = _fake_client(json.dumps({"labs": []}))
    assert extract_labs_from_image(b"fake", rules, client=client) == []


def test_extract_handles_bad_json(rules):
    client = _fake_client("this is not json {")
    assert extract_labs_from_image(b"fake", rules, client=client) == []


def test_extract_handles_missing_text_block(rules):
    """If the response has no text block, return empty rather than crash."""
    response = SimpleNamespace(content=[])
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_kw: response)
    )
    assert extract_labs_from_image(b"fake", rules, client=client) == []


def test_extract_passes_image_and_schema_to_client(rules):
    client = _fake_client(json.dumps({"labs": []}))
    extract_labs_from_image(
        b"png-bytes", rules, client=client, media_type="image/jpeg"
    )

    captured = client.captured  # type: ignore[attr-defined]
    user_msg = captured["messages"][0]
    assert user_msg["role"] == "user"

    image_block = next(b for b in user_msg["content"] if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["type"] == "base64"

    schema = captured["output_config"]["format"]["schema"]
    assert "potassium" in schema["properties"]["labs"]["items"]["properties"]["lab_id"]["enum"]


def test_extract_raises_when_no_api_key(rules, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LabScreenshotError, match="No Anthropic API key"):
        extract_labs_from_image(b"fake", rules)
