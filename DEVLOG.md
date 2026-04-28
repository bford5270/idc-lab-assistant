# Dev Log

Running record of significant development work — written in the "if
I read just this entry I can pick up where I left off" style. Newest
session at the top.

---

## 2026-04-28 — Phases 2–4 closed; ISSO submission packet drafted

**Branch:** `claude/review-idc-work-otGPz` (16 commits ahead of
`main` at session start; not yet merged).
**Test suite:** 249 passing / 0 failing.

### What landed (in commit order — newest first)

| SHA | Title | Phase |
|---|---|---|
| `3cbcb84` | Add run.sh / run.bat launchers + clickable localhost link in README | Local launch ergonomics |
| `ddb7aa7` | Add DEVLOG.md — session pickup notes | Devlog |
| `840afcd` | Add ISSO submission packet (docs/) | Hosting |
| `917cc1f` | Phase 4 commit 3/3: K / Hgb / ALT / LDL / TSH trend interpreters | Phase 4 close |
| `c21871e` | Phase 4 commit 2/3: PSA / Cr / A1C trend interpreters + Prior values UI | Phase 4 |
| `842ff8a` | Phase 4 commit 1/3: trend infrastructure (priors-aware evaluator) | Phase 4 |
| `e6e0bb1` | TB PPD + IGRA risk-stratified interpretation per CDC | Phase 3 close |
| `bd8e188` | PSA age-specific bands per AUA / Oesterling 1993 | Phase 3 |
| `48264fa` | Complete CDC STI panel: GC + CT + trichomonas NAAT + HSV serology | Phase 3 |
| `9583a90` | Syphilis (reverse sequence) + HCV interpreters | Phase 3 |
| `2a6173a` | HIV reactive flow interpreter (CDC algorithm) | Phase 3 |
| `86fc0ae` | Phase 3 scaffolding: Hep B serology interpreter + qualitative schema | Phase 3 |
| `b6101be` | Close Phase 2: trimester-specific TSH, elderly TSH, pregnancy Hgb/ALP/Cr | Phase 2 close |
| `ca0739f` | Anemia workup branching by MCV (micro / normo / macrocytic) | Phase 3 |
| `2202642` | LFT pattern classifier (R-factor): hepatocellular / mixed / cholestatic | Phase 3 |
| `5023ed3` | Pregnancy-conditioned TSH thresholds + fix PREVENT broken-wheel import | Phase 2 |
| `659a39e` | Add albumin-corrected calcium + refresh stale Phase markers | Phase 2 |
| `4ca7858` | Add screenshot upload mode: Claude vision → editable extracted labs | Phase 1 wrap |

### Roadmap state

| Phase | Status |
|---|---|
| Phase 1 (engine + parser rewrite + 21 quantitative labs) | Closed before this session |
| Phase 2 (clinical content + context conditioning) | **Closed this session** at `b6101be` |
| Phase 3 (qualitative interpreters + panel patterns) | **Closed this session** at `e6e0bb1` |
| Phase 4 (trend timeline UI for trend-aware labs) | **Closed this session** at `917cc1f` |

### Engine state highlights

- `pick_thresholds()` lookup order (highest to lowest precedence):
  pregnancy_T<N> → pregnancy → tb_risk_<level> → age_<bracket> →
  elderly → sex → default. Every layer is opt-in per lab via
  `thresholds_by_context` keys.
- **Panel-derived computations** (in `evaluate_panel().derived`):
  bun_cr_ratio + interpretation, anion_gap, eGFR (CKD-EPI 2021),
  CKD G/A/G_A_ stage, KDIGO AKI stage, chronic_ckd_labs_indicated,
  lft_r_factor + pattern + interpretation, anemia_pattern +
  workup, calcium_corrected (attached to the calcium result when
  Ca and albumin both present), AHA PREVENT 2023 ASCVD/CVD/HF risk +
  statin tier.
- **Qualitative interpreters** (`kind: "serology"`, dispatched
  through `evaluate_serology()`): hepatitis_b_serology,
  hiv_serology, syphilis_serology, hepatitis_c_serology,
  gonorrhea_naat, chlamydia_naat, trichomonas_naat, hsv_serology,
  tb_igra. All positive patterns include the full STI co-infection
  cross-reference (HIV / syphilis / HBV / HCV / GC / CT / trichomonas)
  and a preventive medicine consult — enforced by a coverage test in
  `tests/test_serology.py::test_all_serology_labs_have_at_least_one_pattern`.
- **Trend-aware interpreters** (`evaluate(priors=...)` /
  `evaluate_panel(priors_by_lab=...)`, dispatched through
  `_TREND_INTERPRETERS`): PSA velocity, Cr (KDIGO overlay within
  7-day window, chronic uptrend outside it), A1C, K (acute vs
  chronic), Hgb (acute drop / chronic decline / improvement), ALT
  (resolving / persistent / worsening), LDL (high / moderate
  intensity statin response, worsening), TSH (normalization on
  levothyroxine, worsening on therapy, recovery from suppression).
- **PREVENT broken-wheel runtime workaround** (`engine._load_pyprevent`):
  detects the misnamed `.so` from pyprevent 0.1.5, registers it as
  `pyprevent._pyprevent` in `sys.modules`, and retries. No on-disk
  modification of installed packages. Falls through to graceful
  "PREVENT unavailable" if recovery fails.

### Hosting / deployment work

- **`docs/`** folder added with a four-document ISSO submission
  packet (tool description, data-flow diagram, SBOM, PIA shell)
  plus an index README. All explicitly marked DRAFT with bracketed
  `[FIELDS]` for unit-specific information. See `docs/README.md`
  for the suggested submission flow.
- **README.md `## Hosting and PHI`** section is unchanged from
  before — still recommends local install or controlled-infra
  hosting; pre-existing demo-Streamlit-Cloud caveat still applies.

### Local launch ergonomics

- **`run.sh`** (Mac / Linux, executable in git: mode 100755) and
  **`run.bat`** (Windows): double-clickable launchers. Both `cd`
  to the script's own directory, install `requirements.txt` only if
  `streamlit` isn't already on PATH, then run `streamlit run
  app.py`. Streamlit auto-opens the default browser at
  `http://localhost:8501` on first boot.
- **README.md** got a top-of-document "🚀 Launch locally" section
  with the clickable `http://localhost:8501` link (live once the
  server is running) and the three launch options (double-click
  launcher, terminal command, or click the link after boot).
- **Mac Gatekeeper note**: first run of `run.sh` may prompt
  ("can't be opened — unidentified developer"); right-click → Open,
  or System Settings → Privacy & Security → "Open Anyway" once.
  After the first allow, double-click works directly. A
  `run.command` variant could be added if the user prefers the
  Finder-double-click-opens-Terminal-without-prompt pattern; not
  shipped today.

### Open questions / decisions for next session

1. **PR from branch to main** — the 16 commits on
   `claude/review-idc-work-otGPz` haven't been opened as a PR yet.
   Worth doing once the user wants to consolidate; a `/ultrareview`
   pass on the branch first would be valuable given the size.
2. **Deploy posture decision** — three tiers were laid out
   (Streamlit Community Cloud demo, local install per IDC, hosted
   on controlled DoD infra). User has not yet committed to a path.
   The ISSO submission packet is sized for the local-install tier.
3. **Pre-existing PREVENT test failures on main** — fixed on this
   branch via the runtime workaround. If `main` is doing CI, those
   tests will keep failing on `main` until this branch merges.
4. **Anthropic egress policy on government networks** — the
   screenshot upload mode is the only outbound network call in the
   application. The PIA shell flags this for the Component Privacy
   Officer to disposition. If the deployer needs the screenshot
   feature without Anthropic egress, a Tesseract-based on-prem OCR
   fallback was discussed but not implemented; that's a future
   commit if the user requests it.
5. **`requirements.txt` pinning** — currently version-floor only.
   For ISSO-approved deploys, pin to the exact versions listed in
   `docs/03-software-bill-of-materials.md`. The submitted SHA
   should be pinned at install time per that document's
   recommendation.

### Things explicitly out of scope this session (might be future work)

- Multi-lab trend overlays / chart rendering (Phase 4 mentioned
  this as "future layer-on extension").
- Prior-value import from Genesis screenshots (would extend the
  existing screenshot-upload OCR to a different kind of image).
- Pediatric ALP, age-adjusted A1C goals, additional categorical
  contexts — `pick_thresholds` infrastructure already supports
  them, but no `rules.json` content yet.
- Tesseract / on-prem OCR fallback for screenshot mode (alternative
  to Anthropic API call for restricted-network deploys).
- `make pip-audit` / `make install` / `INSTALL.md` for non-developer
  end-users (mentioned at session end as a follow-up).
- Authentication / reverse-proxy front-end for hosted multi-user
  variant (referenced in `docs/02-data-flow-diagram.md` Mode 3 but
  not in this code base).
- Citizen-developer / Power Apps port (raised as one path on DoD
  GCC High; rejected as a poor fit for a Streamlit/Python app).

### Pickup checklist for next session

- [ ] `git fetch && git checkout claude/review-idc-work-otGPz`
- [ ] `python -m pytest` — should report 249 passed / 0 failed
- [ ] Double-click **`run.sh`** (Mac) or **`run.bat`** (Windows) —
      or `streamlit run app.py` — sanity-check that the four tabs
      render at http://localhost:8501: Manual entry, Paste lab
      text, Upload screenshot, Serology
- [ ] Decide direction:
   1. Open a PR `claude/review-idc-work-otGPz` → `main` (after a
      review pass, ideally `/ultrareview`).
   2. Continue layering features (trend chart rendering, additional
      qualitative interpreters, on-prem OCR fallback, install
      tooling).
   3. Move into the hosting / submission workstream — fill in the
      ISSO packet and route to a real ISSO.
