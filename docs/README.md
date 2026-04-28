# IDC Lab Assistant — ISSO Submission Packet

This folder contains draft documentation for submitting the IDC Lab
Assistant to a command's Information Systems Security Officer (ISSO) /
Information Systems Security Manager (ISSM) for software approval on
government-issued workstations.

> **All four documents are drafts.** Replace bracketed `[FIELDS]`
> with your unit-specific information before submitting. The
> Privacy Impact Assessment in particular is a *shell* and must be
> routed to your Component Privacy Officer (DHA Privacy Office for
> medical applications) for adoption as the official record.

## Contents

| File | Purpose |
|---|---|
| [`01-tool-description.md`](01-tool-description.md) | One-page system identification and operational concept. The "lead document" — it's what the reviewer reads first. |
| [`02-data-flow-diagram.md`](02-data-flow-diagram.md) | Every place data enters or leaves the system, in diagram + narrative form. Three modes: default (air-gappable), screenshot upload (single outbound HTTPS call to Anthropic), and a future hosted variant. |
| [`03-software-bill-of-materials.md`](03-software-bill-of-materials.md) | Direct + significant transitive dependencies, licenses, network destinations, known supply-chain notes (including the `pyprevent` 0.1.5 wheel-packaging bug and its runtime workaround). |
| [`04-privacy-impact-assessment.md`](04-privacy-impact-assessment.md) | Shell of a Privacy Impact Assessment per DoDI 5400.16, structured around DD Form 2930 sections. |

## Suggested submission flow

1. **Read everything**, fill in `[FIELDS]`, and pin the `[GIT SHA]`
   you're submitting (e.g., `git rev-parse HEAD`).
2. **Run a vulnerability scan**: `pip-audit` against
   `requirements.txt` is the minimum; your local instruction may
   require ACAS / SCAP / Trivy / Snyk in addition. Record results in
   the SBOM document.
3. **Walk it past your sponsor / clinical lead** for technical
   accuracy of the clinical-content claims (`rules.json` sources)
   before walking it to the ISSO.
4. **Schedule a 30-minute meeting with the ISSO**, send them the
   filled-in packet 24 hours ahead. Bring the four documents
   printed (some ISSOs prefer paper) and a laptop ready to demo the
   tool on synthetic data.
5. **Decide the deployment posture together** — the most likely
   recommended approval is "local install on submitter's workstation
   for de-identified test data only, screenshot mode disabled until
   network egress is approved." That is a real, useful approval that
   lets you start using the tool today and revisit screenshot mode
   later.
6. **If they want a Privacy Officer review**, route the PIA shell
   to the DHA Privacy Office (for DoD-medical applications).

## Things to expect from the ISSO

| Question | Where it's answered |
|---|---|
| What does this tool do? | `01-tool-description.md` §Purpose |
| Who uses it and for what? | `01-tool-description.md` §Identification + §Operational model |
| Does it touch PHI? | `04-privacy-impact-assessment.md` §3 + §6; `02-data-flow-diagram.md` |
| What network connections does it make? | `02-data-flow-diagram.md` Mode 1 / 2 / 3 |
| What dependencies does it have? | `03-software-bill-of-materials.md` |
| Is the tool FDA-cleared? | No — `01-tool-description.md` §Boundaries |
| What's the worst-case data leak? | `04-privacy-impact-assessment.md` §10 |
| Can the screenshot mode be disabled? | Yes — `02-data-flow-diagram.md` Mode 2 (withhold API key) |
| What clinical content is it referencing? | `01-tool-description.md` §Clinical content provenance |
| Test coverage? | 249 automated tests; CI on every push (`.github/workflows/`) |

## After approval

If approved for local install:

```bash
git clone https://github.com/bford5270/idc-lab-assistant.git
cd idc-lab-assistant
# pin to the approved commit:
git checkout [APPROVED GIT SHA]
pip install -r requirements.txt
streamlit run app.py
```

For "no screenshot mode" deployments, simply don't set
`ANTHROPIC_API_KEY` and don't paste a key into the sidebar — the
Extract button will report "no key" and the rest of the application
operates without any outbound network connectivity.

## Maintenance commitments to make to the ISSO

- Pin to a specific git commit at install time; document the hash.
- Run `pip-audit` (or your local equivalent) quarterly.
- Re-submit for review on any major dependency bump or any change
  that adds a new outbound network destination.
- Notify the ISSO if `rules.json` clinical content changes
  materially (this is a clinical-content review, not strictly a
  cybersecurity review).
