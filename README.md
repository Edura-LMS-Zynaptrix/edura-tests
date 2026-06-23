# EDURA Tests — Integration & E2E Testing Suite

This repository contains the cross-service integration tests, end-to-end smoke tests, and load testing scripts that call multiple microservices.

## Setup
Ensure you have the Python environment set up:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running Tests
Run all integration tests:
```bash
pytest
```
