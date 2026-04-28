"""Tests for the Hep B serology interpreter (engine.evaluate_serology).

The fixture rules contain a small synthetic serology lab so the test
suite doesn't depend on the exact pattern bookkeeping in the production
rules.json — but a couple of end-to-end tests do exercise the real
hepatitis_b_serology entry to confirm the schema there matches what
the interpreter expects.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import evaluate_serology, load_rules


@pytest.fixture(scope="module")
def rules() -> dict:
    return load_rules(Path(__file__).parent.parent / "rules.json")


# ---------- Hep B pattern matching ----------


def _hep_b(rules: dict, **markers) -> dict:
    """Helper — markers can be True/False/None, missing keys default to None."""
    inputs = {
        "hbsag": markers.get("hbsag"),
        "anti_hbs": markers.get("anti_hbs"),
        "anti_hbc_total": markers.get("anti_hbc_total"),
        "anti_hbc_igm": markers.get("anti_hbc_igm"),
    }
    return evaluate_serology("hepatitis_b_serology", inputs, rules)


def test_hep_b_susceptible(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=False, anti_hbc_igm=False)
    assert r["pattern_id"] == "susceptible"
    assert r["missing_inputs"] == []


def test_hep_b_vaccinated(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=True, anti_hbc_total=False, anti_hbc_igm=False)
    assert r["pattern_id"] == "vaccinated"


def test_hep_b_resolved_past_infection(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=True, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "resolved_infection"


def test_hep_b_acute_infection(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    assert r["pattern_id"] == "acute_infection"
    assert "acute" in r["category"].lower()


def test_hep_b_chronic_infection(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "chronic_infection"
    assert "hcc" in r["ehr_plan"].lower() or "hepatocellular" in r["ehr_plan"].lower()


def test_hep_b_window_period(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    assert r["pattern_id"] == "window_period"


def test_hep_b_lone_anti_hbc(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "lone_anti_hbc"


def test_hep_b_indeterminate_atypical(rules):
    """HBsAg+ + anti-HBs+ simultaneously is atypical — falls through to
    the indeterminate fallback."""
    r = _hep_b(rules, hbsag=True, anti_hbs=True, anti_hbc_total=True, anti_hbc_igm=False)
    assert r["pattern_id"] == "indeterminate"


# ---------- Missing-input handling ----------


def test_hep_b_partial_inputs_lists_missing(rules):
    """Only HBsAg + anti-HBs available — anti_hbc markers absent. The
    matcher requires all four, so falls to indeterminate, but the
    missing_inputs list helps the IDC see what's needed."""
    r = _hep_b(rules, hbsag=False, anti_hbs=True)
    assert set(r["missing_inputs"]) == {"anti_hbc_total", "anti_hbc_igm"}


def test_hep_b_no_inputs_falls_back_to_indeterminate(rules):
    r = evaluate_serology("hepatitis_b_serology", {}, rules)
    assert r["pattern_id"] == "indeterminate"
    assert len(r["missing_inputs"]) == 4


# ---------- Result shape + sources ----------


def test_hep_b_result_includes_paste_ready_blocks(rules):
    r = _hep_b(rules, hbsag=True, anti_hbs=False, anti_hbc_total=True, anti_hbc_igm=True)
    # Acute pattern fully populated
    assert r["ehr_plan"]
    assert r["patient_communication"]
    assert r["next_tests"]
    assert r["display_name"] == "Hepatitis B Serology"
    assert r["kind"] == "serology"


def test_hep_b_result_includes_sources(rules):
    r = _hep_b(rules, hbsag=False, anti_hbs=False, anti_hbc_total=False, anti_hbc_igm=False)
    assert any("CDC" in s for s in r["sources"])


# ---------- error path ----------


def test_evaluate_serology_rejects_non_serology_lab(rules):
    """Calling with a numeric lab returns an error, not a pattern."""
    r = evaluate_serology("potassium", {"hbsag": True}, rules)
    assert "error" in r
    assert "not a serology lab" in r["error"].lower()


def test_evaluate_serology_unknown_lab(rules):
    r = evaluate_serology("nope_not_a_lab", {}, rules)
    assert "error" in r


# ---------- HIV reactive flow (CDC algorithm) ----------


def _hiv(rules: dict, **markers) -> dict:
    inputs = {
        "ag_ab_screen":        markers.get("ag_ab_screen"),
        "hiv_ab_diff_confirm": markers.get("hiv_ab_diff_confirm"),
        "hiv_1_rna":           markers.get("hiv_1_rna"),
    }
    return evaluate_serology("hiv_serology", inputs, rules)


def test_hiv_non_reactive_screen(rules):
    r = _hiv(rules, ag_ab_screen=False)
    assert r["pattern_id"] == "non_reactive_screen"
    assert "PrEP" in r["ehr_plan"]


def test_hiv_confirmed_infection(rules):
    r = _hiv(rules, ag_ab_screen=True, hiv_ab_diff_confirm=True)
    assert r["pattern_id"] == "confirmed_hiv"
    assert "viral load" in r["ehr_plan"].lower()
    assert "preventive medicine" in r["ehr_plan"].lower()


def test_hiv_acute_infection(rules):
    r = _hiv(rules, ag_ab_screen=True, hiv_ab_diff_confirm=False, hiv_1_rna=True)
    assert r["pattern_id"] == "acute_hiv_1"
    assert "PEP" in r["ehr_plan"] or "pep" in r["ehr_plan"].lower()


def test_hiv_false_reactive_screen(rules):
    r = _hiv(rules, ag_ab_screen=True, hiv_ab_diff_confirm=False, hiv_1_rna=False)
    assert r["pattern_id"] == "false_reactive_screen"


def test_hiv_indeterminate_when_screen_only(rules):
    """Reactive screen with confirmatory not yet done -> indeterminate."""
    r = _hiv(rules, ag_ab_screen=True)
    assert r["pattern_id"] == "indeterminate"
    assert set(r["missing_inputs"]) == {"hiv_ab_diff_confirm", "hiv_1_rna"}


def test_hiv_includes_full_sti_panel_in_positive_pattern(rules):
    """Confirmed HIV should reference the full STI co-infection screen and
    a preventive-medicine consult."""
    r = _hiv(rules, ag_ab_screen=True, hiv_ab_diff_confirm=True)
    plan = r["ehr_plan"].lower()
    for term in ("rpr", "hbv", "hcv", "gc/ct", "trichomonas", "preventive medicine"):
        assert term in plan, f"missing {term} from HIV+ EHR plan"


# ---------- Syphilis (reverse sequence) ----------


def _syphilis(rules: dict, **markers) -> dict:
    inputs = {
        "treponemal_screen": markers.get("treponemal_screen"),
        "rpr_reactive":      markers.get("rpr_reactive"),
    }
    return evaluate_serology("syphilis_serology", inputs, rules)


def test_syphilis_non_reactive(rules):
    r = _syphilis(rules, treponemal_screen=False)
    assert r["pattern_id"] == "non_reactive"


def test_syphilis_active_or_recent(rules):
    r = _syphilis(rules, treponemal_screen=True, rpr_reactive=True)
    assert r["pattern_id"] == "active_or_recent"
    plan = r["ehr_plan"].lower()
    assert "penicillin" in plan
    assert "preventive medicine" in plan
    for term in ("hiv", "hbv", "hcv", "gc/ct", "trichomonas"):
        assert term in plan


def test_syphilis_treponemal_only(rules):
    """Past treated, very late, or treponemal BFP — needs confirmation."""
    r = _syphilis(rules, treponemal_screen=True, rpr_reactive=False)
    assert r["pattern_id"] == "treponemal_only"


def test_syphilis_rpr_only_likely_bfp(rules):
    """RPR+ without treponemal confirmation — likely biological false positive."""
    r = _syphilis(rules, treponemal_screen=False, rpr_reactive=True)
    assert r["pattern_id"] == "rpr_only"


def test_syphilis_indeterminate_when_screen_only(rules):
    r = _syphilis(rules, treponemal_screen=True)
    assert r["pattern_id"] == "indeterminate"


# ---------- Hepatitis C ----------


def _hcv(rules: dict, **markers) -> dict:
    inputs = {
        "anti_hcv": markers.get("anti_hcv"),
        "hcv_rna":  markers.get("hcv_rna"),
    }
    return evaluate_serology("hepatitis_c_serology", inputs, rules)


def test_hcv_non_reactive(rules):
    r = _hcv(rules, anti_hcv=False)
    assert r["pattern_id"] == "non_reactive"


def test_hcv_chronic_active(rules):
    r = _hcv(rules, anti_hcv=True, hcv_rna=True)
    assert r["pattern_id"] == "chronic_active"
    plan = r["ehr_plan"].lower()
    assert "direct-acting antiviral" in plan or "daa" in plan
    assert "preventive medicine" in plan
    for term in ("hiv", "syphilis", "hbv", "gc/ct", "trichomonas"):
        assert term in plan


def test_hcv_resolved(rules):
    r = _hcv(rules, anti_hcv=True, hcv_rna=False)
    assert r["pattern_id"] == "resolved"


def test_hcv_indeterminate_when_anti_hcv_only(rules):
    r = _hcv(rules, anti_hcv=True)
    assert r["pattern_id"] == "indeterminate"


# ---------- GC NAAT ----------


def test_gc_naat_negative(rules):
    r = evaluate_serology("gonorrhea_naat", {"gc_naat_positive": False}, rules)
    assert r["pattern_id"] == "negative"


def test_gc_naat_positive_treats_for_chlamydia(rules):
    r = evaluate_serology("gonorrhea_naat", {"gc_naat_positive": True}, rules)
    assert r["pattern_id"] == "positive"
    plan = r["ehr_plan"].lower()
    assert "ceftriaxone" in plan
    assert "doxycycline" in plan or "azithromycin" in plan
    assert "preventive medicine" in plan


# ---------- CT NAAT ----------


def test_ct_naat_negative(rules):
    r = evaluate_serology("chlamydia_naat", {"ct_naat_positive": False}, rules)
    assert r["pattern_id"] == "negative"


def test_ct_naat_positive_doxycycline_first(rules):
    r = evaluate_serology("chlamydia_naat", {"ct_naat_positive": True}, rules)
    assert r["pattern_id"] == "positive"
    plan = r["ehr_plan"].lower()
    assert "doxycycline" in plan
    assert "preventive medicine" in plan


# ---------- Trichomonas NAAT ----------


def test_trichomonas_naat_negative(rules):
    r = evaluate_serology("trichomonas_naat", {"tv_naat_positive": False}, rules)
    assert r["pattern_id"] == "negative"


def test_trichomonas_naat_positive_metronidazole_7d(rules):
    r = evaluate_serology("trichomonas_naat", {"tv_naat_positive": True}, rules)
    assert r["pattern_id"] == "positive"
    plan = r["ehr_plan"].lower()
    assert "metronidazole" in plan
    # CDC 2021 update — 7d preferred for women over single 2g dose
    assert "7 days" in plan


# ---------- HSV type-specific serology ----------


def _hsv(rules: dict, **markers) -> dict:
    inputs = {
        "hsv_1_igg": markers.get("hsv_1_igg"),
        "hsv_2_igg": markers.get("hsv_2_igg"),
    }
    return evaluate_serology("hsv_serology", inputs, rules)


def test_hsv_no_exposure(rules):
    r = _hsv(rules, hsv_1_igg=False, hsv_2_igg=False)
    assert r["pattern_id"] == "no_exposure"


def test_hsv_1_only(rules):
    r = _hsv(rules, hsv_1_igg=True, hsv_2_igg=False)
    assert r["pattern_id"] == "hsv_1_only"


def test_hsv_2_only_includes_prep_offer(rules):
    """HSV-2+ should mention PrEP given increased HIV acquisition risk."""
    r = _hsv(rules, hsv_1_igg=False, hsv_2_igg=True)
    assert r["pattern_id"] == "hsv_2_only"
    plan = r["ehr_plan"].lower()
    assert "prep" in plan
    assert "preventive medicine" in plan


def test_hsv_dual(rules):
    r = _hsv(rules, hsv_1_igg=True, hsv_2_igg=True)
    assert r["pattern_id"] == "hsv_dual"


# ---------- TB IGRA ----------


def test_tb_igra_negative(rules):
    r = evaluate_serology("tb_igra", {"igra_result": False}, rules)
    assert r["pattern_id"] == "negative"


def test_tb_igra_positive(rules):
    r = evaluate_serology("tb_igra", {"igra_result": True}, rules)
    assert r["pattern_id"] == "positive"
    plan = r["ehr_plan"].lower()
    assert "chest x-ray" in plan or "cxr" in plan
    assert "preventive medicine" in plan
    assert "rifampin" in plan or "isoniazid" in plan


def test_tb_igra_indeterminate(rules):
    r = evaluate_serology("tb_igra", {}, rules)
    assert r["pattern_id"] == "indeterminate"


# ---------- Coverage check: every serology lab is reachable ----------


def test_all_serology_labs_have_at_least_one_pattern(rules):
    for lab_id, lab_def in rules["labs"].items():
        if lab_def.get("kind") != "serology":
            continue
        assert lab_def.get("patterns"), f"{lab_id} has no patterns"
        for p in lab_def["patterns"]:
            assert "id" in p and "label" in p, f"{lab_id} pattern missing id/label"
            # Every positive pattern (anything not 'negative' / 'non_reactive' /
            # 'no_exposure' / 'vaccinated' / 'susceptible' / 'resolved*') should
            # reference preventive medicine — STI cross-reference convention.
            negative_ids = {
                "negative", "non_reactive", "no_exposure",
                "non_reactive_screen", "vaccinated", "susceptible",
                "resolved_infection", "resolved",
                # patterns that suggest the test was a false positive
                # (no real infection, no contact tracing needed):
                "false_reactive_screen", "rpr_only",
            }
            if p["id"] in negative_ids:
                continue
            plan = (p.get("ehr_plan") or "").lower()
            assert "preventive medicine" in plan, (
                f"{lab_id}.{p['id']} missing preventive medicine consult"
            )
