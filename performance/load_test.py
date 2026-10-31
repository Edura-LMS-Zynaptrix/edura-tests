#!/usr/bin/env python3
"""
Performance tests for EDURA (guideline 10.1 item 9; SRS NFR-001 and NFR-009).

Two modes, both read-only (public GET endpoints, no data is created):

  latency  Sends paced requests through the public gateway and reports response times.
           Checks NFR-001: 95% of interactions answered in under 2.0 seconds. The gateway
           allows 100 requests per minute per IP (burst 20), so the pace stays below it.
  load     Closed-loop concurrency steps (for example 1, 10, 25, 50, 100 workers) against
           PERF_BASE_URL. One client IP cannot exceed the gateway limit, so for this mode
           point PERF_BASE_URL at a service reached by `kubectl port-forward`.
           Checks the NFR-009 trend: response time and error rate as concurrency grows.

Usage:
  PERF_BASE_URL=https://staging.eduralms.com python performance/load_test.py latency
  PERF_BASE_URL=http://localhost:18003 PERF_PATHS=/api/courses/ python performance/load_test.py load
Writes performance/results/<mode>.json and prints a Markdown table.
"""

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.getenv("PERF_BASE_URL", "https://staging.eduralms.com").rstrip("/")
# Public, read-only endpoints. Override with PERF_PATHS="/a,/b".
DEFAULT_PATHS = [
    "/api/courses/",
    "/api/courses/11",
    "/api/analytics/platform-stats",
    "/api/enrollments/class-packages",
]
PATHS = [p for p in os.getenv("PERF_PATHS", ",".join(DEFAULT_PATHS)).split(",") if p]
THRESHOLD_SECONDS = 2.0  # NFR-001
LATENCY_REQUESTS = int(os.getenv("PERF_LATENCY_REQUESTS", "20"))  # per endpoint
LATENCY_INTERVAL = float(
    os.getenv("PERF_LATENCY_INTERVAL", "0.8")
)  # seconds between requests
STEPS = [int(s) for s in os.getenv("PERF_STEPS", "1,10,25,50,100").split(",")]
STEP_SECONDS = float(os.getenv("PERF_STEP_SECONDS", "20"))
# Stop stepping up once a step looks unhealthy, so the test cannot knock a small server over.
ABORT_ERROR_PCT = float(os.getenv("PERF_ABORT_ERROR_PCT", "10"))
ABORT_P95_SECONDS = float(os.getenv("PERF_ABORT_P95_SECONDS", "5"))
REQUEST_TIMEOUT = float(os.getenv("PERF_REQUEST_TIMEOUT", "10"))
RESULTS = Path(__file__).parent / "results"
FAILURES = {}  # transport failures by exception name (status 0 in the tables)


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def summarise(durations, statuses):
    total = len(statuses)
    ok = sum(1 for s in statuses if s == 200)
    return {
        "requests": total,
        "ok": ok,
        "errors": total - ok,
        "rate_limited": sum(1 for s in statuses if s == 429),
        "status_counts": {str(c): statuses.count(c) for c in sorted(set(statuses))},
        "error_rate_pct": round(100 * (total - ok) / total, 1) if total else 0.0,
        "p50_ms": round(1000 * percentile(durations, 50)),
        "p95_ms": round(1000 * percentile(durations, 95)),
        "p99_ms": round(1000 * percentile(durations, 99)),
        "mean_ms": round(1000 * statistics.fmean(durations)) if durations else 0,
        "under_2s_pct": (
            round(
                100
                * sum(1 for d in durations if d < THRESHOLD_SECONDS)
                / len(durations),
                1,
            )
            if durations
            else 0.0
        ),
    }


async def timed_get(client, path):
    start = time.perf_counter()
    try:
        res = await client.get(f"{BASE_URL}{path}")
        status = res.status_code
    except httpx.HTTPError as exc:
        status = 0
        FAILURES[type(exc).__name__] = FAILURES.get(type(exc).__name__, 0) + 1
    return time.perf_counter() - start, status


async def run_latency():
    rows = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for path in PATHS:
            await timed_get(
                client, path
            )  # warm-up (connection and caches), not counted
            await asyncio.sleep(LATENCY_INTERVAL)
            durations, statuses = [], []
            for _ in range(LATENCY_REQUESTS):
                d, s = await timed_get(client, path)
                durations.append(d)
                statuses.append(s)
                await asyncio.sleep(LATENCY_INTERVAL)
            rows[path] = summarise(durations, statuses)
    return rows


async def worker(client, deadline, durations, statuses, offset):
    i = offset
    while time.perf_counter() < deadline:
        d, s = await timed_get(client, PATHS[i % len(PATHS)])
        durations.append(d)
        statuses.append(s)
        i += 1


async def run_load():
    rows = {}
    for users in STEPS:
        durations, statuses = [], []
        limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, limits=limits, follow_redirects=True
        ) as client:
            started = time.perf_counter()
            deadline = started + STEP_SECONDS
            await asyncio.gather(
                *(
                    worker(client, deadline, durations, statuses, n)
                    for n in range(users)
                )
            )
            elapsed = time.perf_counter() - started
        row = summarise(durations, statuses)
        print(f"  {users} users: statuses {row['status_counts']}", flush=True)
        row["throughput_rps"] = round(row["requests"] / elapsed, 1)
        rows[str(users)] = row
        if (
            row["error_rate_pct"] > ABORT_ERROR_PCT
            or row["p95_ms"] > 1000 * ABORT_P95_SECONDS
        ):
            row["stopped_here"] = True
            print(
                f"stopping after {users} users: error rate {row['error_rate_pct']}%, p95 {row['p95_ms']} ms"
            )
            break
        await asyncio.sleep(8)  # let the service settle between steps
    return rows


def table(mode, rows):
    if mode == "latency":
        head = "| Endpoint | Requests | Errors | p50 ms | p95 ms | p99 ms | Under 2 s |\n|---|---|---|---|---|---|---|\n"
        body = "".join(
            f"| `{k}` | {v['requests']} | {v['errors']} | {v['p50_ms']} | {v['p95_ms']} | {v['p99_ms']} | {v['under_2s_pct']}% |\n"
            for k, v in rows.items()
        )
    else:
        head = "| Concurrent users | Requests | Errors | Throughput req/s | p50 ms | p95 ms | p99 ms |\n|---|---|---|---|---|---|---|\n"
        body = "".join(
            f"| {k} | {v['requests']} | {v['errors']} ({v['error_rate_pct']}%, {v['rate_limited']} rate-limited) | {v['throughput_rps']} | {v['p50_ms']} | {v['p95_ms']} | {v['p99_ms']} |\n"
            for k, v in rows.items()
        )
    return head + body


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "latency"
    if mode not in ("latency", "load"):
        sys.exit("usage: load_test.py latency|load")
    rows = asyncio.run(run_latency() if mode == "latency" else run_load())
    out = {
        "mode": mode,
        "base_url": BASE_URL,
        "paths": PATHS,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
    }
    print(f"\n{mode} test against {BASE_URL}\n")
    print(table(mode, rows))
    if FAILURES:
        print(f"\ntransport failures: {FAILURES}")
    print(json.dumps(out))
    try:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / f"{mode}.json").write_text(json.dumps(out, indent=2))
    except OSError:
        pass  # a read-only folder (for example a mounted ConfigMap) must not lose the printed results


if __name__ == "__main__":
    main()
