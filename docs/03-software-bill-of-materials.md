# IDC Lab Assistant — Software Bill of Materials (SBOM)

> **DRAFT — for ISSO / ISSM submission.** Versions reflect the
> environment used to develop and test the version at commit
> `[GIT SHA]`. Production deploys should pin to these or later
> patched versions and run `pip-audit` before each deploy.

## Direct dependencies (declared in `requirements.txt`)

| Package | Version | License | Purpose | Maintainer | Notes |
|---|---|---|---|---|---|
| `streamlit` | 1.56.0 | Apache-2.0 | Web UI framework | Snowflake (Streamlit Inc.) | Mainstream OSS; widely used in DoD and federal data-science teams |
| `matplotlib` | 3.10.9 | matplotlib license (BSD-style) | Severity-band bar charts | NumFOCUS | Mainstream scientific-computing library |
| `anthropic` | 0.97.0 | MIT | Anthropic API client (screenshot mode only) | Anthropic | Used only by `lab_screenshot.py`; not loaded if screenshot mode is unused |
| `pyprevent` | 0.1.5 | MIT | AHA PREVENT 2023 cardiovascular risk calculator | nference (third party) | **See "Known issues" below** — wheel packaging bug on Linux/Python 3.11 is worked around at runtime in `engine.py:_load_pyprevent` |

## Development-only dependencies (declared in `requirements-dev.txt`)

| Package | Version | License | Purpose |
|---|---|---|---|
| `pytest` | 9.0.3 | MIT | Test runner; not installed in production deployments |

## Significant transitive dependencies

These are pulled in automatically by the direct dependencies. None
are introduced for application functionality outside what the direct
dependencies need. Listed for supply-chain transparency.

| Package | Version | License | Pulled in by |
|---|---|---|---|
| `pandas` | 3.0.2 | BSD-3-Clause | streamlit |
| `numpy` | 2.4.4 | BSD-3-Clause | matplotlib, pandas |
| `pillow` | 12.2.0 | MIT-CMU (HPND) | streamlit, matplotlib |
| `httpx` | 0.28.1 | BSD-3-Clause | anthropic |
| `pydantic` | 2.13.3 | MIT | anthropic |
| `anyio` | 4.13.0 | MIT | anthropic, httpx |
| `jiter` | 0.14.0 | MIT | anthropic (JSON parsing) |
| `tornado` | 6.5.5 | Apache-2.0 | streamlit (web server) |
| `protobuf` | 7.34.1 | BSD-3-Clause | streamlit |
| `altair` | 6.1.0 | BSD-3-Clause | streamlit (charts) |
| `gitpython` | 3.1.47 | BSD-3-Clause | streamlit (auto-detects git for hosted deploys) |

A complete `pip freeze` output of the developer environment is
captured at `[ATTACHMENT — paste pip freeze output here for the
exact submission environment]`.

## Source language

- Application source: Python 3.11+ (tested on 3.11.x)
- No compiled extensions in our own code
- One transitive native binary: `pyprevent` ships a Rust extension
  (`.so` on Linux). See "Known issues" below.

## Network destinations

| Destination | When called | Reason | Disable how |
|---|---|---|---|
| `api.anthropic.com` (HTTPS) | When IDC clicks "Extract" in the Upload-screenshot tab | Vision OCR of de-identified lab-table screenshots | Don't provide an `ANTHROPIC_API_KEY` (sidebar field stays blank); the Extract button gracefully reports "no key" |
| (No others) | — | — | — |

The application makes **no other outbound network calls** in any
mode. It does not phone home, send telemetry, or check for updates.

## Known issues / supply-chain notes

### `pyprevent` 0.1.5 wheel packaging bug

The published wheel of `pyprevent` 0.1.5 installs its compiled Rust
extension under the wrong filename on Linux/Python 3.11
(`pyprevent.cpython-<tag>.so` instead of
`_pyprevent.cpython-<tag>.so`). Without intervention, `import
pyprevent` raises `ImportError`.

**Mitigation**: `engine.py:_load_pyprevent()` detects this case at
runtime, locates the misnamed extension via
`importlib.util.find_spec`, loads it as a module, registers it under
`sys.modules["pyprevent._pyprevent"]`, and retries the package import.
This workaround:

- Does **not modify any installed package on disk**.
- Does **not require write permission to site-packages**.
- Falls through to the application's existing "PREVENT unavailable"
  graceful-degradation path if the workaround fails (the calculator
  is simply marked unavailable in the UI; the rest of the app works).

The behaviour is covered by automated tests
(`tests/test_engine.py::test_prevent_*`).

### Pinning strategy

`requirements.txt` does not pin upper bounds, on the assumption that
ISSO-approved deployments will pin specific versions at deploy time.
For the submitted commit, the recommended pinned versions are the
ones in the table above.

For DoD-hardened deploys, an Iron Bank rebuild of these dependencies
(or the equivalent harden process the reviewer specifies) should be
substituted.

## Vulnerability scanning

The submitter has run / commits to running:

- `pip-audit` against the dependency set on `[DATE]` — `[NO ISSUES /
   ISSUES NOTED BELOW]`.
- `[ANY OTHER REQUIRED SCANS — e.g., snyk, trivy, ACAS, SCAP per
   local instruction]`.

## License summary

All direct and significant transitive dependencies are under
permissive open-source licenses (MIT, BSD, Apache-2.0, or
matplotlib/PIL HPND-style). No copyleft (GPL/AGPL) dependencies are
present. License-file pointers are available in each package's
distribution metadata via
`pip show <package> | grep License`.

## Update policy

- Dependency review cadence: `[QUARTERLY / PER POLICY]`.
- Security-update channel: pin to upstream PyPI releases; subscribe
  to `[SOURCE — e.g., GitHub security advisories on the mirrored
  repo]`.
- Re-review trigger: any major-version bump or any CVE listed
  against a direct dependency.
