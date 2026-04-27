# IDC Lab Assistant

A clinical decision-support tool for Independent Duty Corpsmen (IDCs) that
takes lab values, classifies severity, and produces paste-ready EHR plan
language and patient communication — including emergency-department
direction language at critical tiers.

> **De-identified data only.** Do not paste PHI/PII into this tool. See
> [Hosting and PHI](#hosting-and-phi) below before using on real patient data.

---

## What it does

Given a lab value (typed manually or pasted as free-text), the tool:

1. **Classifies severity** on a single ladder — `Normal → Mild → Moderate →
   Severe → Critical`, with a directional suffix (`Severe Low` / `Severe
   High`) where appropriate.
2. **Returns a structured follow-up** for that severity:
   - `category` — short clinical label
   - `next_tests` — recommended workup
   - `ehr_plan` — paste-ready clinician note with `{value}` slots auto-filled
     and `[bracket]` placeholders left for the IDC to complete
   - `patient_communication` — paste-ready, plain-language patient message,
     with explicit ED-direction language at Severe / Critical tiers
3. **Surfaces clinical reasoning prompts** for labs where workup branches
   (currently creatinine — AKI vs CKD vs AKI-on-CKD).
4. **Plots the value** against the severity bands.

## Phase 1 lab set (21 labs)

- **Electrolytes / renal:** Na, K, Cl, HCO3, BUN, Cr, Ca, Mg, P
- **Glucose / endocrine:** glucose, A1C, TSH
- **Liver / protein:** ALT, AST, ALP, total bilirubin, albumin
- **CBC:** WBC, Hgb, MCV, platelets

Threshold cutoffs are anchored to current guidelines (KDIGO, ADA, AABB,
AASLD, AAFP, ATA, ASH) — see the `sources` field per lab in
[`rules.json`](rules.json).

## Quick start

```bash
git clone https://github.com/bford5270/idc-lab-assistant.git
cd idc-lab-assistant
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Two input modes:

- **Manual entry** — pick a lab from the dropdown and enter a value.
- **Paste lab text** — paste lab data, one lab per line (`K 6.2`,
  `Glucose 320`, etc.).

The optional sidebar (sex, age, pregnancy) sharpens sex-stratified bands
(Hgb, Cr, ALT, AST). When sex is not provided, the engine falls back to
conservative default bands and flags the assumption in the output.

## Repository layout

```
rules.json              Canonical rules — thresholds + follow-up content
engine.py               Pure engine: load_rules, evaluate, render_template
lab_parser.py           Free-text parser (line-by-line, word-boundary)
app.py                  Streamlit UI
requirements.txt        Runtime deps (streamlit, matplotlib)
requirements-dev.txt    Dev deps (pytest)
tests/                  Pytest suite for engine + parser
.github/workflows/      CI: pytest on every push to main
```

## Hosting and PHI

This is a clinical decision-support tool, not a substitute for clinical
judgment, and it is not currently hosted in a HIPAA / DoD-approved
environment. **Use de-identified or test data only.**

If you want IDCs to use this on real patient data, the canonical path is:

- **Run locally** on the IDC's own workstation (`streamlit run app.py`),
  with no data leaving the machine; or
- **Re-host behind authentication** on government / controlled
  infrastructure (e.g. CAC-authenticated, behind a DoD network boundary).

A public Firebase / Streamlit Community Cloud deployment is fine for
demos with synthetic data but is not appropriate for real clinical use.

## Roadmap

Phase 1 (current) — schema rebuild, engine + parser rewrite, 21
quantitative labs with structured follow-up.

Phase 2 — clinical content corrections, broader patient-context
conditioning (age, pregnancy where guidelines differ), interactive
rendering of the creatinine differentiation block.

Phase 3 — qualitative interpreters (Hep B serology, syphilis sequence,
HIV reactive flow, TB risk-stratified PPD, PSA age-specific), plus
panel-level interpretation (anion gap auto-compute, LFT pattern
classifier, anemia workup branching on MCV).

Phase 4 — per-lab "+ Add prior value" timeline UI for trend-aware labs
(Cr/eGFR, A1C, PSA, K, Hgb, LFTs, lipids, TSH); KDIGO AKI staging when
a baseline is supplied.

## Disclaimer

This tool is provided as-is for clinical decision support and educational
use. It is not FDA-cleared. Always apply clinical judgment. The authors
make no warranty regarding fitness for any particular use, including
clinical use on real patients.
