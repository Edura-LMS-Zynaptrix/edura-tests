# EDURA Tests — Integration & E2E Testing Suite

This repository contains the cross-service integration tests, end-to-end smoke tests, and load testing scripts that call multiple microservices.

## Setup
Ensure you have the Python environment set up:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration
Copy `.env.example` to `.env`, fill in the required secrets and load it:
```bash
cp .env.example .env
set -a; source .env; set +a
```
`SECRET_KEY` and `PAYHERE_MERCHANT_SECRET` have no defaults; the tests fail fast if they are missing. In CI the deploy pipeline (`edura-infra`) supplies them from GitHub Secrets, and this repo's own CI uses throwaway mock values.

## Running Tests
Run all integration tests:
```bash
pytest
```
