# IDC Lab Assistant — Privacy Impact Assessment (PIA) Shell

> **DRAFT — for ISSO / ISSM / Privacy Officer submission.** This is a
> shell of a PIA per DoDI 5400.16 / DD Form 2930. It is not a formal
> PIA — replace bracketed `[FIELDS]` with unit-specific information
> and route to the responsible Component Privacy Officer
> (e.g., DHA Privacy Office for medical applications) for adoption
> as the official record.

## Section 1 — System identification

| Field | Value |
|---|---|
| System name | IDC Lab Assistant |
| Acronym | IDC-LA |
| Version | `[GIT COMMIT SHA]` |
| Date of submission | `[YYYY-MM-DD]` |
| System owner | `[ORGANIZATION / COMMAND]` |
| Privacy Officer of record | `[NAME / OFFICE / EMAIL]` |
| ISSO of record | `[NAME / OFFICE / EMAIL]` |
| Sponsor | `[NAME / OFFICE / EMAIL]` |

## Section 2 — System description

### 2.1 What does the system do?

The IDC Lab Assistant is a Python / Streamlit clinical-decision-support
reference tool. It accepts a numeric lab value (typed manually,
pasted as text, or extracted from an uploaded screenshot) along with
optional patient context (sex, age, pregnancy, diabetic status, TB
risk category, baseline creatinine), and returns a structured
interpretation: severity tier, recommended workup, paste-ready EHR
plan language, paste-ready patient communication, and trend analysis
when prior values are supplied.

### 2.2 What does the system NOT do?

- It does not connect to any DoD information system, EHR (MHS
  Genesis, AHLTA), or laboratory information system.
- It does not make autonomous medical decisions.
- It does not transmit any data to or from any patient.
- It does not persist any input or output to disk, database, or
  cloud storage.

### 2.3 Operational concept

Clinicians (Independent Duty Corpsmen) use the tool as a reference
during sick call. They enter de-identified or synthetic test values
and copy the structured output back into the patient record by hand
in the EHR (out-of-band of this system).

## Section 3 — Information collected

### 3.1 Categories of data the system can accept

| Category | Example | Sensitivity per system policy |
|---|---|---|
| Numeric lab values | "K = 5.4 mEq/L" | Synthetic / de-identified only |
| Free-text lab paste | "Sodium 138, Potassium 4.5" | Synthetic / de-identified only |
| Lab-table screenshot | PNG / JPG image | Synthetic / de-identified only |
| Patient context (categorical) | sex, age (integer), pregnant (Y/N), trimester (1/2/3), diabetic (Y/N), TB risk category, prior creatinine + date, urine ACR | Synthetic / de-identified only |
| Cardiovascular risk inputs | systolic BP, BMI, smoker (Y/N), on-meds flags | Synthetic / de-identified only |
| Prior lab values for trend analysis | (value, ISO date) tuples per lab | Synthetic / de-identified only |

### 3.2 Data the system does NOT collect

- **No direct identifiers**: name, DoD ID number, SSN, MRN, DOB,
  date of service, address, phone, email — none are accepted by any
  input field. There are no fields for these. Pasting them into a
  free-text field would technically place them in process memory
  briefly, but the application's PHI banner explicitly prohibits this
  and no logic stores or retrieves identifiers.
- **No biometrics**.
- **No PHI per the HIPAA Privacy Rule** is intended to be entered
  per the system's policy.

### 3.3 PHI policy enforcement

- A high-visibility warning banner is rendered at the top of every
  session: "**De-identified test data only.** This is a clinical
  decision support tool. Do not paste PHI/PII. Use clinical judgment
  — this tool does not replace it."
- The Upload-screenshot tab's caption restates this: "The image is
  sent to Claude vision once for parsing — **de-identified data
  only**, same policy as the rest of the tool. Review and correct
  values before evaluating."
- IDC user training (developed alongside this submission) covers
  the same policy.

## Section 4 — Sources of information

| Source | Description |
|---|---|
| The user | All numeric and contextual input is typed, pasted, or uploaded by the IDC. The system has no other input source. |

## Section 5 — Use of information

The information entered is used to:

1. Compute a severity classification by comparing to threshold tables.
2. Render structured guidance text per the matched severity.
3. Compute panel-derived values (anion gap, BUN/Cr, eGFR, CKD stage,
   AKI stage, LFT R-factor, anemia pattern, PREVENT risk).
4. Compute trend metrics when priors are supplied.
5. Display all of the above on the user's local screen.

The information is **not** used for research, training of any model,
billing, surveillance, performance management, or any secondary use.

## Section 6 — Disclosure of information

### 6.1 Local-only modes (Manual entry, Paste lab text)

**No disclosure.** The information stays inside the local Python
process and the user's browser. No network egress.

### 6.2 Upload-screenshot mode (optional feature)

If — and only if — the user clicks "Extract" in the Upload-screenshot
tab and an Anthropic API key is configured, the screenshot is
transmitted to Anthropic, PBC over HTTPS to be parsed into structured
text via Claude vision.

| Recipient | Anthropic, PBC |
|---|---|
| Mechanism | HTTPS POST to `api.anthropic.com/v1/messages` (TLS 1.2+) |
| Contents | Base64-encoded image bytes + system prompt + JSON-schema constraint |
| Anthropic data-handling | API inputs are not used to train models by default per Anthropic's published policy (see https://trust.anthropic.com). DoD HIPAA / privacy obligations are NOT outsourceable to Anthropic — therefore the system policy independently forbids PHI in screenshots. |
| Disable | Withhold the API key (sidebar field empty AND `ANTHROPIC_API_KEY` env var unset). The Extract button will report "no key" and refuse to send. |

`[REQUIRED FOR ADOPTION: review by Component Privacy Officer of
whether the Anthropic outbound flow is acceptable for the intended
deployment posture. If not, the recommended mitigation is to disable
the screenshot tab in the deployed build.]`

### 6.3 Logs and audit

- The application writes no application logs to disk. Streamlit
  writes start-up messages to stdout/stderr; these contain no patient
  data.
- For hosted deploys, the host platform's standard request logging
  (e.g., reverse-proxy access logs) applies per the host's policy.

## Section 7 — Notice to individuals

This system has no end-customer ("data subject") relationship — it
is used by clinicians on de-identified test data, not on patients
directly. Therefore standard data-subject notice provisions are not
applicable in the operational mode.

User-facing notice to the IDC user is provided by the in-application
PHI banner (Section 3.3).

## Section 8 — Access controls

| Control | Default mode | Hosted variant |
|---|---|---|
| Authentication | None (host workstation login is the access boundary) | CAC + reverse proxy (per host policy) |
| Authorization | None at the application layer | Group membership at the proxy layer |
| Audit | None at the application layer | Per host platform |
| Encryption in transit | Loopback only (no remote traffic) | TLS at the proxy |
| Encryption at rest | N/A (no persistent storage) | N/A (no persistent storage) |
| Secrets handling | API key from env var or in-memory sidebar field; not persisted | Secrets manager + injected env var |

## Section 9 — Data retention and disposal

- **Application memory**: cleared when the user closes the browser
  tab or terminates the host process.
- **Disk**: nothing is written.
- **Logs**: stdout only; cleared with the host process.

No retention schedule is required because no records are retained.

## Section 10 — Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| User pastes real PHI into a text field despite policy | Medium | Medium (PHI in process memory until session ends; if screenshot mode + Anthropic call follows, PHI would egress) | PHI banner; tab caption restates; required user training; recommend disabling screenshot mode in deployed build until egress policy is signed off |
| Screenshot contains embedded PHI (text in image, EXIF metadata) | Medium | High | Banner + training; future enhancement to strip EXIF client-side; recommend disabling screenshot mode where Anthropic egress is not approved |
| Anthropic API key disclosure | Low | Medium | Key is `type="password"` in UI; never logged; never persisted; recommend per-IDC keys, not shared host keys |
| MITM on Anthropic call | Very low | Medium | TLS 1.2+; SDK validates certificates |
| Dependency supply-chain compromise | Low | Medium | SBOM in `03-software-bill-of-materials.md`; recommend periodic `pip-audit` or equivalent SCA scan; pinned versions at deploy |
| Tampering with `rules.json` (clinical content) | Low (host-controlled) | Medium (could produce wrong guidance) | Out of scope for the application; relies on host workstation security; deploy from a known git commit and validate hash before use |
| Network egress on default mode | None (no egress in default mode) | N/A | Default mode is air-gappable |

## Section 11 — Privacy Officer review

`[TO BE COMPLETED BY COMPONENT PRIVACY OFFICER]`

| Item | Disposition |
|---|---|
| PIA required? | `[YES / NO / N/A — DECISION + RATIONALE]` |
| If yes, PIA category | `[FULL / ABBREVIATED]` |
| System of Records Notice (SORN) required? | `[YES / NO]` (likely no — no records retained) |
| HIPAA Privacy Rule applicability | `[Discuss whether covered-entity status of the deploying organization brings the tool into scope despite no PHI flow by policy]` |
| Approved disposition | `[APPROVED / APPROVED WITH CONDITIONS / DISAPPROVED]` |
| Conditions | `[ENUMERATE]` |
| Signature / date | `[NAME, DATE]` |

## Section 12 — References

- DoDI 5400.16, *DoD Privacy Impact Assessment (PIA) Guidance*
- DoDI 8500.01, *Cybersecurity*
- DoDI 8510.01, *Risk Management Framework (RMF) for DoD Information Technology*
- DoDM 8530.01, *DoD Cybersecurity Activities Support Procedures*
- HIPAA Privacy Rule, 45 CFR Parts 160, 164
- Anthropic Trust Center, https://trust.anthropic.com
- Application source repository: https://github.com/bford5270/idc-lab-assistant
