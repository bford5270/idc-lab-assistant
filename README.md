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
- **CDC STI panel — qualitative interpreters** built on the
  `kind: "serology"` schema + `evaluate_serology` engine function +
  Serology tab. Every positive pattern surfaces the full STI
  co-infection screen (HIV, syphilis, HBV, HCV, GC, CT, trichomonas)
  and a preventive medicine consult for partner notification +
  public-health reporting:
  - **Hepatitis B serology** (HBsAg / anti-HBs / anti-HBc total /
    IgM) → 7 named patterns + indeterminate per CDC + AASLD 2018.
  - **HIV reactive flow** (4th-gen Ag/Ab → HIV-1/HIV-2 differentiation
    → HIV-1 RNA) per CDC algorithm: non-reactive, confirmed, acute
    HIV-1 (antibody-negative window), false-reactive screen,
    indeterminate.
  - **Syphilis (reverse sequence)** (treponemal screen → reflex
    non-treponemal RPR) per CDC + MMWR 2011: non-reactive, active /
    recent, treponemal-only (past treated / late / BFP), RPR-only
    (likely BFP), indeterminate.
  - **Hepatitis C** (anti-HCV → reflex RNA): non-reactive, chronic
    active (links to direct-acting antiviral therapy), resolved,
    indeterminate.
  - **Gonorrhea NAAT**: positive triggers ceftriaxone 500 mg IM ×1
    + empiric chlamydia treatment per CDC 2021.
  - **Chlamydia NAAT**: positive triggers doxycycline 100 mg BID ×7d
    (or azithromycin 1 g ×1 in pregnancy, doxycycline ×21 days for
    LGV proctitis) per CDC 2021.
  - **Trichomonas NAAT**: positive triggers metronidazole 500 mg BID
    ×7 days for women / pregnancy (preferred over single 2 g dose
    per CDC 2021 update); 2 g ×1 for men.
  - **HSV type-specific serology** (HSV-1 IgG / HSV-2 IgG): no
    exposure / HSV-1 only / HSV-2 only (offers PrEP given increased
    HIV acquisition risk) / dual.
- **TB PPD / IGRA** with risk-stratified interpretation per CDC:
  - **TB PPD** (numeric induration mm) with risk-stratified bands —
    high (≥5 mm: HIV+ / recent contact / immunosuppressed),
    moderate (≥10 mm: high-prevalence-country immigrants <5y, IV
    drug users, congregate settings, lab workers, certain medical
    conditions, children <4), low (≥15 mm: no risk factors). New
    sidebar "TB risk category" selector drives the cutoff.
  - **TB IGRA** (QuantiFERON / T-SPOT) — negative / positive /
    indeterminate. Both PPD positive and IGRA positive trigger the
    same workup (CXR + symptom screen, sputum AFB if symptomatic,
    HIV / HBV / HCV / CMP / LFT baseline, preventive medicine
    contact-tracing consult, LTBI treatment per CDC 2020 — rifampin
    4 months preferred, or 3HP × 12 weekly DOT, or INH 6–9 months).
- **PSA age-specific bands** per AUA / Oesterling: 40–49 (<2.5),
  50–59 (<3.5), 60–69 (<4.5), 70+ (<6.5). Severity ladder ranges
  Mild High through Critical High (≥20 ng/mL — bone scan + CT +
  urology/oncology referral). Default band (no age) keeps the
  classic <4.0 cutoff.

**Phase 2 — closed.** Pregnancy and age-adjusted thresholds shipped
above. Future per-lab context expansions (pediatric ALP, sex/age PSA
bands, etc.) live in Phase 3 alongside the qualitative interpreters.

**Phase 3 — closed.** Qualitative interpreters and risk-stratified
panels shipped above. Future Phase-3-style content (additional STIs,
TB drug susceptibility, urine dipstick patterns, etc.) lives in
Phase 4 alongside the trend timeline UI.

**Phase 4 — trends:**
- Per-lab "+ Add prior value" timeline UI for trend-aware labs
  (Cr/eGFR, A1C, PSA, K, Hgb, LFTs, lipids, TSH).

## Disclaimer

This tool is provided as-is for clinical decision support and educational
use. It is not FDA-cleared. Always apply clinical judgment. The authors
make no warranty regarding fitness for any particular use, including
clinical use on real patients.
