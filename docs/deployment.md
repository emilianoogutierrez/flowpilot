# Deployment

## Containerized local demonstration

The Compose file defines PostgreSQL, a one-shot migration/demo initializer, the API and a worker. The console is built in a Node stage and served from the Python image. The exposed port binds only to loopback.

```bash
python scripts/bootstrap.py
docker compose up --build
```

Open http://localhost:8000 and use the generated demo credentials. The database persists in a named Docker volume. `docker compose down` stops containers; `docker compose down -v` destroys the demonstration database.

The supplied Compose configuration is intended for development and staging validation, not as an Internet-facing production recipe. Validate the container build, PostgreSQL behavior, TLS termination, backups and deployment-specific network policy in the target environment before production use.

## Image shape

The image runs under a non-root application account. The Compose API and worker use read-only root filesystems with a temporary `/tmp`, no added Linux capabilities and no-new-privileges. `.env`, local databases and verification output are excluded from the build context.

Base image major-version tags can move. Pin reviewed digests and run a current image/dependency vulnerability scan for deployment. The local requirements lock is exact for the tested core environment, not a complete image provenance attestation.

## Production gate

Set `FLOWPILOT_ENVIRONMENT=production`, use a PostgreSQL URL, HTTPS public origin, trusted hostnames, secure cookies and a long random metrics token. Remove `--demo` from initialization and create separate operator accounts. Terminate TLS at a configured reverse proxy. Preserve the real Host header, limit request size/time, and configure trusted proxy handling deliberately.

Run the real PostgreSQL tests and native HTTP browser tests. Validate concurrent workers, migration application, backup restore, provider authentication, network egress, cancellation and uncertain side-effect recovery. Restrict outbound traffic at the network level. Keep DNS, internal metadata services and private networks out of reach of workflow nodes.

Secrets must come from protected deployment configuration or a secrets manager. Never bake `.env` into images or commit it. Set a separate retention and access policy for audit records and backups.

No public deployment URL is claimed by this repository. An operator must complete and record these checks for the actual target environment.
