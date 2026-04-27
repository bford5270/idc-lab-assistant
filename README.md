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

The app opens in your browser. Three input modes:

- **Manual entry** — pick a lab from the dropdown and enter a value.
- **Paste lab text** — paste lab data, one lab per line (`K 6.2`,
  `Glucose 320`, etc.).
- **Upload screenshot** — drop a screenshot of a lab table (e.g. from
  Genesis); Claude vision parses it into structured values that the IDC
  reviews and corrects before evaluating. Requires an Anthropic API key
  (paste in the sidebar or set `ANTHROPIC_API_KEY`). Uses
  `claude-haiku-4-5` by default. Same de-identified-only policy as the
  rest of the tool — do not upload screenshots that contain PHI.

The optional sidebar (sex, age, pregnancy) sharpens sex-stratified bands
(Hgb, Cr, ALT, AST). When sex is not provided, the engine falls back to
conservative default bands and flags the assumption in the output.

## Repository layout

```
rules.json              Canonical rules — thresholds + follow-up content
engine.py               Pure engine: load_rules, evaluate, render_template
lab_parser.py           Free-text parser (line-by-line, word-boundary)
lab_screenshot.py       Vision-based lab extraction (Claude API)
app.py                  Streamlit UI
requirements.txt        Runtime deps (streamlit, matplotlib, anthropic)
requirements-dev.txt    Dev deps (pytest)
tests/                  Pytest suite for engine, parser, and screenshot module
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

**Shipped:**
- Phase 1 — schema rebuild, engine + parser rewrite, 21 quantitative labs
  with structured follow-up.
- KDIGO eGFR (CKD-EPI 2021), CKD G/A staging, KDIGO AKI staging when a
  baseline Cr is supplied.
- Panel-level computations: anion gap, BUN/Cr ratio with prerenal /
  intrinsic interpretation, albumin-corrected calcium.
- Glucose `follow_up_by_context` (diabetic vs default) with diabetic
  status driven from the sidebar.
- Creatinine differentiation: structured baseline-Cr / UACR inputs,
  computed eGFR / CKD G_A_ stage, AKI stage, chronic-CKD-panel trigger
  at G3a.
- Lipid panel + AHA PREVENT 2023 10-year ASCVD / CVD / HF risk with
  statin-intensity recommendation per ACC/AHA.
- Screenshot upload mode: Claude vision parses lab-table screenshots
  into editable structured values.
- Pregnancy-conditioned thresholds (Phase 2 closure):
  - **TSH** with trimester-specific bands per ATA 2017 — T1 Normal
    0.3–2.5, T2 0.3–3.0, T3 0.4–3.0; trimester selector in the
    sidebar; generic pregnancy band as fallback when trimester unknown.
  - **Hemoglobin** with anemia floor at 11 g/dL per ACOG (vs 12 for
    non-pregnant female).
  - **Alkaline phosphatase** with Normal extending to 260 U/L
    (placental ALP physiologically raises ALP 2–3× in pregnancy).
  - **Creatinine** with Normal 0.4–0.9 mg/dL and elevated threshold
    at 1.1 mg/dL per ACOG preeclampsia criteria (pregnancy GFR rises
    ~50%, lowering Cr).
- Age-conditioned TSH thresholds: at age ≥70, the engine selects an
  elderly band with Normal extending to 5.0 mIU/L per ATA hypothyroidism
  guidance on age-related TSH rise. Pregnancy outranks elderly when
  both apply.
- LFT pattern classifier (R-factor): when ALT and ALP are both in the
  panel, the engine computes R = (ALT/ALT_ULN) / (ALP/ALP_ULN) and
  classifies hepatocellular (R>5) / mixed (2–5) / cholestatic (R<2)
  per AASLD/EASL DILI guidance, with workup language surfaced under
  ALT, AST, and ALP results plus the session-derived block.
- Anemia workup branching by MCV: when Hgb is below normal and MCV is
  in the panel, the engine classifies microcytic (<80) / normocytic
  (80–100) / macrocytic (>100) and surfaces pattern-specific workup
  (iron studies for micro; reticulocyte + smear for normo;
  B12/folate/TSH for macro).

**Phase 2 — closed.** Pregnancy and age-adjusted thresholds shipped
above. Future per-lab context expansions (pediatric ALP, sex/age PSA
bands, etc.) live in Phase 3 alongside the qualitative interpreters.

**Phase 3 — qualitative interpreters + panel patterns:**
- Hep B serology (HBsAg / anti-HBs / anti-HBc / IgM).
- Syphilis sequence (treponemal / non-treponemal RPR titer).
- HIV reactive flow (4th-gen Ag/Ab → confirmatory).
- TB PPD risk-stratified induration cutoffs.
- PSA age-specific bands.

**Phase 4 — trends:**
- Per-lab "+ Add prior value" timeline UI for trend-aware labs
  (Cr/eGFR, A1C, PSA, K, Hgb, LFTs, lipids, TSH).

## Disclaimer

This tool is provided as-is for clinical decision support and educational
use. It is not FDA-cleared. Always apply clinical judgment. The authors
make no warranty regarding fitness for any particular use, including
clinical use on real patients.
