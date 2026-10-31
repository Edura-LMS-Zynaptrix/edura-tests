# UI end-to-end tests

Browser tests for the three critical flows (guideline §6.2), run with [Playwright](https://playwright.dev) against a deployed environment.

| # | Flow | Spec |
|---|---|---|
| 1 | Register, confirm the email, sign in (and a refused wrong password) | `tests/01-register-and-login.spec.ts` |
| 2 | Search the catalogue, enrol in a free course, open checkout for a paid course | `tests/02-browse-and-enrol.spec.ts` |
| 3 | Enrol, take an exam, submit it, see the result | `tests/03-take-exam.spec.ts` |

Each spec follows Given-When-Then naming and Arrange-Act-Assert structure. Every run creates its own throw-away student (an address in Resend's test inbox, which delivers nothing) and removes the account and enrolment afterwards through the admin API. Payment stops at the checkout page; no money moves.

## Run

```bash
cd e2e
npm ci
npx playwright install --with-deps chromium
set -a; source ../.env; set +a      # SECRET_KEY must equal the target environment's
STAGING_WEB_URL=https://staging.eduralms.com npx playwright test
```

`SECRET_KEY` stands in for the inbox (it signs the email-verification link, as `auth_service` does) and for an admin (cleanup). It is read from the environment and is never committed. Reports are written to `playwright-report/` and `results/junit.xml`.

The suite targets seeded staging data: free course 11 (with exams) and paid course 10. Update the ids at the top of the specs if the catalogue changes.
