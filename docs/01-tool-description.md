# IDC Lab Assistant — Tool Description

> **DRAFT — for ISSO / ISSM submission.** Replace bracketed
> `[FIELDS]` with your unit-specific information before submitting.

## Identification

| Field | Value |
|---|---|
| **System name** | IDC Lab Assistant |
| **System type** | Clinical decision-support utility (reference tool) |
| **Repository** | https://github.com/bford5270/idc-lab-assistant |
| **Version reviewed** | `[GIT COMMIT SHA OF VERSION BEING SUBMITTED]` |
| **Submitter** | `[NAME / RANK / COMMAND / EMAIL]` |
| **Sponsor / supervisor** | `[NAME / RANK / TITLE]` |
| **Intended user population** | Independent Duty Corpsmen (IDCs) and analogous clinical roles |
| **Intended deployment scope** | `[LOCAL INSTALL ON ISSUED LAPTOP / CLINIC-WIDE / OTHER]` |

## Purpose

The IDC Lab Assistant is a reference tool that converts a numeric lab
value (typed manually, pasted as free-text, or extracted from an
uploaded screenshot) into a structured clinical interpretation:

- A severity classification on a single ladder
  (`Normal → Mild → Moderate → Severe → Critical`).
- A recommended workup (next tests / orders).
- Paste-ready EHR plan language with `{value}` slots auto-filled and
  bracketed `[fill-ins]` for the IDC.
- Paste-ready patient communication including explicit
  emergency-department-direction language at Severe / Critical tiers.
- Panel-derived values when multiple labs are present (anion gap,
  BUN/Cr ratio, eGFR, KDIGO AKI staging, LFT R-factor, anemia
  classification by MCV, AHA PREVENT 2023 cardiovascular risk).
- Pattern-based interpretation for qualitative serology / NAAT
  (Hepatitis B, HIV, syphilis, Hepatitis C, gonorrhea, chlamydia,
  trichomonas, HSV, TB IGRA).
- Trend-aware interpretation when prior values are supplied
  (PSA velocity, KDIGO AKI delta, A1C trajectory, statin response,
  TSH treatment response, etc.).

## Boundaries — what the tool does NOT do

- It is **not FDA-cleared** and is not a substitute for clinical
  judgment.
- It is **not connected to any EHR** (MHS Genesis, AHLTA, etc.).
  All input is manual or copy-paste; all output is read-only text the
  IDC copies back into the EHR by hand.
- It is **not connected to any laboratory information system** and
  receives no automatic feed.
- It does **not** make autonomous treatment decisions, place orders,
  or transmit data to any patient.
- It does **not** persist any patient data to disk, database, or
  cloud storage. All state is in process memory and is destroyed when
  the user closes the application.
- It does **not** require, request, or process PHI/PII per its own
  policy (banner displayed at the top of every session restates this).

## Operational model

- **Where it runs**: locally, as a Streamlit web application bound
  by default to `localhost`. Each user runs the application on their
  own issued workstation. The browser session is on the same machine.
- **What's installed**: Python 3.11+ runtime, ~10 third-party Python
  packages from the Python Package Index (full list in
  `03-software-bill-of-materials.md`), and the application source.
- **Network connectivity** (full diagram in `02-data-flow-diagram.md`):
  - **Default mode** (manual entry, paste lab text): zero outbound
    network traffic. Application is fully air-gappable.
  - **Screenshot upload mode** (optional feature): sends one image
    per IDC click to `api.anthropic.com` over HTTPS for OCR. The
    application's PHI banner explicitly forbids uploading screenshots
    that contain PHI/PII; the OCR is intended for de-identified test
    data only. **This mode can be disabled** by either (a) not
    providing an API key, or (b) `[FUTURE BUILD FLAG, IF NEEDED]`.
- **Authentication**: none in the default local-use model (the host
  workstation's login is the access boundary). For multi-user
  deployments, the application is designed to sit behind a reverse
  proxy that enforces authentication (e.g., CAC + oauth2-proxy).
- **Logging**: the application writes no application logs to disk.
  Streamlit's stdout/stderr stream is the only output and contains no
  patient data.

## Clinical content provenance

Every threshold, follow-up, and interpretation in the rules file
(`rules.json`) cites its source. Sources include:

- KDIGO 2012 AKI / 2024 CKD guidelines
- ADA Standards of Care
- AABB transfusion threshold
- AASLD 2023 MASLD guidance + ACG 2017 abnormal liver chemistries
- ATA 2014 hypothyroidism / 2017 pregnancy thyroid guidelines
- AHA PREVENT 2023 (Khan et al., *Circulation*)
- AUA 2023 prostate cancer early detection
- CDC STI Treatment Guidelines 2021 (with 2024 updates)
- CDC LTBI Guide for Primary Care Providers (2020)

Test coverage: 249 automated tests (engine, parser, screenshot
extractor, serology interpreters, trend interpreters) run in CI on
every push.

## Risk classification (proposed)

| Question | Proposed answer | Rationale |
|---|---|---|
| Does the system process PHI? | No (per policy) | PHI banner; no persistence; de-identified-only use enforced by user-facing notice |
| Does the system make autonomous medical decisions? | No | Output is reference text; clinician interprets and acts |
| Does the system integrate with any DoD information system? | No | Standalone; no EHR / LIS connection |
| Does the system require external network connectivity? | Optional (one feature) | Screenshot mode only; can be disabled |
| Software supply-chain category | Open-source Python (PyPI) | All dependencies are mainstream OSS (Streamlit, matplotlib, anthropic SDK, pyprevent) |
| Encryption in transit | Yes | Streamlit HTTPS for hosted deployments; Anthropic API uses TLS 1.2+ |
| Encryption at rest | N/A | No persistent storage |

## Requested action

`[CHOOSE ONE OR ADAPT]`

- [ ] Approval for **local install on the submitter's issued
      workstation** for **de-identified test data only**, with
      screenshot upload mode `[ENABLED / DISABLED]`.
- [ ] Approval for **clinic-wide local install** by named IDCs,
      with the same data-handling policy.
- [ ] Approval for **interim Authority to Operate (iATO)** as a
      limited-use research / pilot tool under
      `[CITE LOCAL INSTRUCTION]`.
- [ ] Other: `[DESCRIBE]`.

## Points of contact

| Role | Name | Email | Phone |
|---|---|---|---|
| Submitter / system owner | `[NAME]` | `[EMAIL]` | `[PHONE]` |
| Technical POC | `[NAME]` | `[EMAIL]` | `[PHONE]` |
| Clinical sponsor | `[NAME]` | `[EMAIL]` | `[PHONE]` |
| ISSO | `[NAME]` | `[EMAIL]` | `[PHONE]` |
