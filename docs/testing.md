# Testing

The suite concentrates on state transitions and trust boundaries. Coverage is a diagnostic for missing exercised code, not a target that substitutes for meaningful assertions.

## Fast checks

```bash
python -m pip install -e ".[dev]"
npm ci
python scripts/check.py
```

The backend tests create temporary SQLite databases and apply actual Alembic migrations. They do not reuse the demonstration database. Provider and transport tests use labeled synthetic fixtures, not recordings containing credentials.

## Test groups

| Group | Evidence |
| :--- | :--- |
| Definition | Node contracts, references, DAG rejection, bounded schemas and reserved headers |
| Crypto | Envelope authentication, wrong-context rejection, tampering and key rotation |
| HTTP | URL policy, private DNS answers, TLS host pinning, redirects, bounded bodies and retry classification |
| Providers | Normalized OpenAI, Anthropic and Gemini requests/responses, refusal and malformed output |
| API | Sessions, CSRF, roles, tenant boundaries, revision conflicts, webhooks, credentials and queue admission |
| Worker | Durable waits, lease loss, stale results, concurrent claims, cancellation and safe side effects |
| Migrations | Upgrade, downgrade, repeat upgrade and metadata parity |
| PostgreSQL | Real concurrent row-lock and duplicate-admission tests; opt-in environment |
| Console | Strict TypeScript, pure-function unit tests and browser interaction walkthrough |

## PostgreSQL

Install the `postgres` extra. Set `TEST_DATABASE_URL` to a disposable PostgreSQL database whose user can create schemas. Tests create and drop randomly named schemas. They do not clear an existing schema, but should never run against a production account.

```bash
python -m pip install -e ".[postgres,dev]"
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost/flowpilot_test python -m pytest -m postgres
```

Without that variable, these tests report **skipped**, not passed. SQLite thread tests do not prove PostgreSQL locking behavior.

## Process-level HTTP checks

```bash
python scripts/http_smoke.py
```

This creates a temporary database and launches a separate API and worker. It verifies real loopback HTTP, static asset delivery, session cookies, origin rejection, version publication, duplicate admission, durable approval and logout. It is independent of browser navigation restrictions.

## Browser checks

```bash
python -m playwright install chromium
python scripts/browser_smoke.py
```

The normal mode launches an isolated local application, browser and worker. It requires native browser HTTP navigation. For a restricted rendering environment:

```bash
python scripts/browser_smoke.py --bridge --chromium /usr/bin/chromium
```

Bridge mode still executes the compiled console, real FastAPI routes, authentication checks, database mutations and worker operations. Only fetch transport, the CSRF cookie view and session storage are supplied by a test harness. It does **not** validate native browser cookie policy, CSP enforcement, module serving or the production network. Its report names the mode explicitly.

Use `--screenshots docs/assets` to regenerate example screenshots. They contain synthetic demo data. Do not use this command against private customer workspaces.

## Benchmark

```bash
python scripts/benchmark.py --runs 100
```

The default benchmark uses a temporary SQLite database, one worker and local set/condition nodes. It records queue drain time, throughput and end-to-end latency including queue wait. It is a repeatable smoke workload, not a capacity claim for PostgreSQL, live AI or concurrent production traffic.

## Dependency and style tools

Ruff and mypy are part of the development toolchain and should be run together with the test suite before merging changes. The frontend TypeScript check is separate from Python static typing. Dependency advisory scanning requires an up-to-date vulnerability database and should run in CI or before deployment.

Refer to [the actual results](../verification/REPORT.md), not to the mere presence of a test or CI file, when describing this project's verification.
