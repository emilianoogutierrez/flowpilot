# Verification snapshot

This document records a local verification snapshot for FlowPilot 0.1.0. It is not a production certification, penetration test or guarantee that all defects have been found.

## Verified locally

| Check | Result |
| :--- | :--- |
| Python backend tests | 147 passed, 3 PostgreSQL-only tests skipped, 0 failed |
| Python statement coverage | 90.57% (1699 / 1876 statements) |
| TypeScript strict checking | Passed |
| Frontend build | Passed |
| Frontend unit tests | 4 passed |
| Browser interaction walkthrough | 14 checks passed in the documented bridge mode |
| Separate-process HTTP smoke | 10 checks passed over loopback HTTP |
| Local execution benchmark | 100 runs completed with three local nodes per run |
| Editable source installation | Passed with the installed dependency set |
| Python source compilation | Passed |

The backend suite covers API behavior, tenant and role boundaries, workflow validation, envelope encryption, credential rotation, HTTP transport policy, AI adapter contracts, durable execution, recovery, idempotency, migrations and CLI operations.

## Browser verification boundary

The deterministic browser walkthrough runs the compiled console against real FastAPI routes, a temporary database and the execution worker through a test bridge. It exercises sign-in, workflow filtering, graph rendering, definition validation, durable approval, replay, publication, cancellation, credential lifecycle, project creation, audit history, a narrow viewport and sign-out.

This mode does not prove native browser cookie policy, CSP enforcement, same-site behavior, HTTP module loading or reverse-proxy behavior. `scripts/browser_smoke.py` also supports a normal browser mode for use in an unrestricted local environment.

The separate `scripts/http_smoke.py` starts an API process and a worker process and exercises real loopback HTTP, static delivery, authenticated cookies, cross-origin mutation rejection, publication, duplicate admission, worker progress, approval and logout.

## Reliability and security coverage

Tests cover duplicate submissions, stale revisions, immutable workflow versions, lease expiration, interrupted attempts, late-result fencing, bounded retries, durable delays, approvals and cancellation. Scheduler fairness is covered against saturated workflows, and worker lease timestamps are checked against the database clock. Unsafe side effects with uncertain outcomes are not blindly repeated.

Security-focused tests cover organization scoping, permission failures, session revocation, CSRF/origin checks, request and response limits, JSON contract rejection, authenticated encryption, secret redaction, blocked private addresses, TLS hostname validation and redirect refusal. These are implementation checks, not an independent security audit.

## Benchmark

The recorded workload uses SQLite, one worker, 100 pre-admitted runs and three local nodes per run. It performs no network I/O and calls no external AI provider.

| Measurement | Observed |
| :--- | ---: |
| Admission time | 0.2696 seconds |
| Queue drain time | 2.7042 seconds |
| Completed runs per second | 36.98 |
| Queue-inclusive p50 latency | 2594.93 ms |
| Queue-inclusive p95 latency | 2693.96 ms |
| Queue-inclusive p99 latency | 2700.70 ms |

Treat these numbers as a repeatable local smoke workload, not as PostgreSQL capacity, HTTP throughput, customer scale or real AI latency. The benchmark source is `scripts/benchmark.py`.

## Checks that remain deployment-specific

| Check | Requirement |
| :--- | :--- |
| PostgreSQL concurrency | Disposable PostgreSQL database and the `postgres` extra |
| Docker/Compose startup | Docker with Compose |
| Native browser walkthrough | Normal browser/Playwright environment |
| Live AI provider calls | Operator-owned provider credentials and allowed egress |
| Live TLS/SSRF exercise | Controlled external endpoints and deployment egress rules |
| OTLP export | Running collector |
| Dependency advisory scan | Current vulnerability database |
| Backup/restore rehearsal | Staging database, real backup process and protected keys |

Before a public deployment, validate these checks in the target environment and review `docs/security.md`, `docs/operations.md` and `docs/deployment.md`.

## Reproduce the local checks

```bash
python -m pip install -e ".[dev]"
npm ci
python scripts/check.py
python scripts/http_smoke.py
python -m playwright install chromium
python scripts/browser_smoke.py
python scripts/benchmark.py --runs 100
```

PostgreSQL tests require the disposable database described in `docs/testing.md`.
