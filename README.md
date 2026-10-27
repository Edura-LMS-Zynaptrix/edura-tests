# EDURA Tests — Integration & E2E Testing Suite

[![Tests CI](https://github.com/Edura-LMS-Zynaptrix/edura-tests/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Edura-LMS-Zynaptrix/edura-tests/actions/workflows/ci.yml)

This repository contains the cross-service integration tests, end-to-end smoke tests, and load testing scripts that call multiple microservices of the EDURA Learning Management System (LMS). It is one part of the EDURA project:

| Repository | Contents |
|---|---|
| [edura-backend](https://github.com/Edura-LMS-Zynaptrix/edura-backend) | The 11 FastAPI microservices |
| [edura-frontend](https://github.com/Edura-LMS-Zynaptrix/edura-frontend) | Next.js web application |
| [edura-infra](https://github.com/Edura-LMS-Zynaptrix/edura-infra) | Docker Compose, Nginx gateway, Kubernetes manifests and deploy pipeline |
| **edura-tests** (this repo) | Integration, smoke and performance tests |
| [edura-documents](https://github.com/Edura-LMS-Zynaptrix/edura-documents) | SRS, SDS, ADRs, retrospectives and test evidence |

> **Coverage badge:** this repository holds the tests themselves and no product code, so it has no code-coverage figure. The coverage badges for the product are on the [edura-backend](https://github.com/Edura-LMS-Zynaptrix/edura-backend#readme) and [edura-frontend](https://github.com/Edura-LMS-Zynaptrix/edura-frontend#readme) READMEs.

## Deployed application

The tests call a running EDURA system through its gateway. By default they use `http://localhost`; point them at a deployed environment with the `STAGING_API_URL` variable.

| Environment | URL |
|---|---|
| Staging | https://staging.eduralms.com |
| Production | https://eduralms.com |

The smoke test runs automatically against staging after every staging deploy (see `edura-infra/.github/workflows/deploy.yml`).

## Contents

| Folder | Purpose |
|---|---|
| `smoke/critical_path.py` | End-to-end smoke test of the student journey (register, verify, log in, enrol, view a course) |
| `integration/` | Pytest integration tests, for example the PayHere payment to enrollment flow |
| `performance/` | Load tests (Locust) and the scripts that run and analyse them |

## Prerequisites

* [Git](https://git-scm.com/)
* [Python 3.12](https://www.python.org/downloads/)
* A running EDURA system to test against: the local Docker stack (see the [edura-backend README](https://github.com/Edura-LMS-Zynaptrix/edura-backend#run-the-system-locally-step-by-step)) or a deployed environment such as staging
* For the performance tests only: [Locust](https://locust.io/) (`pip install locust`)

## Setup (step by step)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Edura-LMS-Zynaptrix/edura-tests.git
   cd edura-tests
   ```
2. **Create a virtual environment and install the dependencies:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Configure the environment.** Copy `.env.example` to `.env`, fill in the required secrets and load it:
   ```bash
   cp .env.example .env
   set -a; source .env; set +a        # Windows PowerShell: set each variable with $env:NAME = "value"
   ```
   Set `STAGING_API_URL` to choose the system under test (default `http://localhost`), for example `https://staging.eduralms.com`.

## Running the tests

Run all integration tests:
```bash
pytest integration -v
```

Run the end-to-end smoke test:
```bash
python smoke/critical_path.py
```

### Environment variables

`SECRET_KEY` and `PAYHERE_MERCHANT_SECRET` are required and have no defaults; the tests stop with a clear message if they are missing. Set them to the values the system under test uses. The other variables have defaults that match the local development setup:

| Variable | Used for | Default |
|---|---|---|
| `STAGING_API_URL` | Gateway URL under test | `http://localhost` |
| `SECRET_KEY` | JWT signing key of the target system | **required** |
| `PAYHERE_MERCHANT_SECRET` | Signing the simulated PayHere webhook | **required** |
| `PAYHERE_MERCHANT_ID` | Merchant ID used in the simulated webhook | sandbox value |
| `SMOKE_TEST_OTP` | OTP accepted by integration tests | `123456` |
| `SMOKE_EMAIL_DOMAIN` / `SMOKE_EMAIL_USER` | Address used for smoke-test sign-ups | `resend.dev` / `delivered` |
| `SMOKE_EVENT_WAIT_SECONDS` | How long to wait for asynchronous events | `30` |

Do not commit real secrets. The smoke job in `edura-infra` reads them from the GitHub environment secrets, and this repository's own **Tests CI** sets throwaway mock values because it runs against the in-process mock transport.

## Continuous integration

Every pull request and every push to `main`, `develop` and `feature/**` runs the **Tests CI** workflow: a syntax and lint check of the smoke and integration scripts, and the payment and enrollment integration tests on pushes and pull requests that target `develop` or `main`.

## Branching and releases

`main` and `develop` are protected branches; changes reach `develop` through a reviewed pull request from a `feature/<ticket-id>-<slug>` branch. Releases follow Semantic Versioning (`vMAJOR.MINOR.PATCH`).
