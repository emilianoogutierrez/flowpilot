# Local development

## Requirements

Python 3.12 or 3.13 and pip are required. Node 22 is used for console development; the checked-in static build does not require Node at runtime. Initial dependency installation needs package-index access.

The recorded verification environment used Python 3.13.5, Node 22.16.0 and TypeScript 5.8.3. Core Python dependencies are pinned to the tested environment in `requirements.lock`. PostgreSQL and developer tools are separate extras; this is not a universal cross-platform, hash-locked supply-chain guarantee.

## Source installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python scripts/dev.py
```

Run commands from the repository root. Editable installation is intentional: migrations, examples and the compiled console are checked-in project files. A standalone wheel deployment without these files is not supported by this release.

On Windows, invoke `.venv\Scripts\python.exe` directly or activate with `.venv\Scripts\Activate.ps1`. No shell-policy changes are necessary when using the interpreter directly.

## Configuration

`scripts/bootstrap.py` creates random encryption keys, a metrics token, a demo password and a container database password. It creates `.env` exclusively and never overwrites it. `.env.example` documents shape, but its placeholder keys cannot start the application.

| Setting | Meaning |
| :--- | :--- |
| `FLOWPILOT_DATABASE_URL` | SQLite source mode or PostgreSQL using `postgresql+psycopg://` |
| `FLOWPILOT_MASTER_KEYS` | JSON object of key IDs to base64url-encoded 32-byte master keys |
| `FLOWPILOT_ACTIVE_KEY_ID` | Key used to wrap new encrypted records |
| `FLOWPILOT_PUBLIC_ORIGIN` | Exact browser origin, including port; no trailing slash |
| `FLOWPILOT_ALLOWED_HOSTS` | JSON array of trusted HTTP Host values |
| `FLOWPILOT_EGRESS_HOSTS` | JSON array of exact external hostnames; empty denies network nodes |
| `FLOWPILOT_SECURE_COOKIES` | Must be true behind HTTPS in production |
| `FLOWPILOT_LEASE_SECONDS` | Default 90; keep comfortably above node timeout and expected DB latency |
| `FLOWPILOT_POLL_SECONDS` | Worker idle polling delay |
| `FLOWPILOT_MAX_QUEUED_RUNS` | Non-terminal execution cap per workspace |
| `FLOWPILOT_RETENTION_DAYS` | History cutoff used by the explicit purge command |
| `FLOWPILOT_METRICS_TOKEN` | Bearer token for the metrics endpoint |
| `FLOWPILOT_OTLP_ENDPOINT` | Optional trusted OTLP HTTP trace receiver |

All settings are validated at startup. The process environment overrides `.env`. Do not send configuration files or real secrets to a chat or issue.

## Commands

```bash
python -m flowpilot.cli init
python -m flowpilot.cli init --demo
python -m flowpilot.cli create-user person@example.test --name "Example User" --organization "Example team"
python -m flowpilot.cli reset-password person@example.test
python -m flowpilot.cli validate examples/lead-triage.json
python -m flowpilot.cli export-schema
python -m flowpilot.cli worker
```

User creation and password reset read passwords interactively. `init` applies Alembic migrations. `--demo` refuses production mode. To run processes separately:

```bash
python -m uvicorn flowpilot.api.app:create_app --factory --host 127.0.0.1 --port 8000
python -m flowpilot.cli worker
```

## Editing the console

```bash
npm ci
npm run typecheck
npm run build
npm test
```

There is no runtime bundler or frontend dependency server. Rebuild, then reload the console. `web/dist` is included so source downloads remain easy to try. Commit the rebuilt output alongside source changes.

## Common issues

**Origin rejected:** use the exact URL configured in `FLOWPILOT_PUBLIC_ORIGIN`. `localhost` and `127.0.0.1` are different origins. Do not disable CSRF to work around it.

**Invalid encryption key:** run bootstrap on a fresh configuration or provision a valid 32-byte key. Copying `.env.example` without replacing placeholders is not sufficient.

**No worker progress:** check a separate worker is running and inspect workspace heartbeats. The API can be ready without an execution worker.

**Credential unavailable:** check provider kind, project, current revocation state and the definition's credential ID. Creating a credential does not allow a new egress destination automatically.

**HTTP host denied:** add only the exact trusted destination to operator configuration, restart the API and workers, then configure the credential binding. Do not permit an arbitrary proxy host.

**Python build dependency missing:** an isolated, offline environment may need preinstalled setuptools. `pip install --no-build-isolation --no-deps -e .` is useful only when the required build tools are already installed. Do not use it to hide missing runtime dependencies.
