# Performance tests

`load_test.py` measures response time and behaviour under concurrent load (guideline §10.1 item 9; SRS NFR-001 and NFR-009). Both modes only send GET requests to public endpoints, so no data is created.

```bash
pip install -r requirements.txt

# NFR-001: paced requests through the gateway; reports p50/p95/p99 and the share under 2.0 s
PERF_BASE_URL=https://staging.eduralms.com python performance/load_test.py latency

# NFR-009: concurrency steps (default 1, 10, 25, 50, 100 workers, 20 s each)
PERF_BASE_URL=https://staging.eduralms.com python performance/load_test.py load
```

Settings (environment variables): `PERF_BASE_URL`, `PERF_PATHS` (comma-separated), `PERF_LATENCY_REQUESTS`, `PERF_LATENCY_INTERVAL`, `PERF_STEPS`, `PERF_STEP_SECONDS`. Results are written to `performance/results/<mode>.json` (git-ignored) and printed as a Markdown table.

**Limit of the public gateway.** The gateway allows 100 requests per minute per IP (burst 20), so one machine cannot generate real load through it: most requests in `load` mode come back as HTTP 429, and that is counted as `rate-limited`, not as a failure of a service. To measure the services' own capacity, point `PERF_BASE_URL` at a service reached with `kubectl port-forward`, or use several client IPs. See `edura-documents/testing/performance-report.md` for the results and what they do and do not show.
