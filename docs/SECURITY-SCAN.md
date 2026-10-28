# Lint, format and security scan

The **Tests Quality** workflow (`.github/workflows/quality.yml`) implements the Lint &
Format and Security Scan stages of development guideline section 7.2 for this
repository. The functional tests run in the separate **Tests CI** workflow.

## Lint & Format

Runs on every push to any branch.

| Check | Files | Config |
|---|---|---|
| Ruff (lint) | `integration/`, `smoke/` | `pyproject.toml`, same rules as `edura-backend` |
| Black (format) | `integration/`, `smoke/` | `pyproject.toml` |

Run locally before committing: `ruff check .` and `black --check .`

Cyclomatic complexity (rule `C901`) is not enforced for `integration/` and `smoke/`,
because the end-to-end flows and the in-process mock gateway are long, linear scenarios.
Every other rule applies.

## Security Scan

Runs on every pull request to `develop` or `main` and on every push to those branches.
`scripts/security-scan.sh` runs `pip-audit` on `requirements.txt` and fails on any known
vulnerability that is not in `security/accepted-vulnerabilities.txt`.

### Policy: dependencies are not changed to pass the scan

If the scan fails because of a vulnerability, the team does **not** change or pin
dependencies just to make the check green. The advisory is reviewed and, if the risk is
acceptable, added to the accepted list with a reason. This is the same approach as
ADR-14 in `edura-documents`. These dependencies are used only to run tests and are not
part of the deployed product.

### How to bypass a failing check

1. Find the advisory ID in the job log (for example `PYSEC-2024-1234` or
   `GHSA-xxxx-xxxx-xxxx`).
2. Decide whether it is acceptable: is the vulnerable code reachable in the tests?
3. Add one line to `security/accepted-vulnerabilities.txt`:

   ```
   <advisory ID>  <reason; owner; review date>
   ```

4. Raise a pull request. The reviewer must agree with the reason. Never accept an
   advisory without a written reason and a review date.
5. Remove the line once the dependency is fixed or no longer used.

Accepted advisories are printed in the job log on every run, so they stay visible. They
do not fail the build; any **new** advisory does.

### Currently accepted advisories

None. `security/accepted-vulnerabilities.txt` is the single source of truth; update this
table when an advisory is accepted.

| Advisory | Package | Reason | Owner | Review date |
|---|---|---|---|---|
| (none) | | | | |
