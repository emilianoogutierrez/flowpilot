# HTTP API

The machine-readable contract is [openapi.json](openapi.json), also served at `/api/openapi.json`. Development-only `/api/docs` uses Swagger UI's external assets and therefore needs browser internet access. The main console itself does not.

## Session and workspace

Sign in through `POST /api/v1/auth/login` with `email` and `password`. The server sets an HttpOnly session cookie and an `fp_csrf` cookie. Mutating authenticated requests must echo the CSRF value in `X-CSRF-Token`. Requests with an Origin header must match the configured origin.

After `GET /api/v1/auth/me`, select a permitted workspace using `X-Workspace-ID`. The server checks membership on every workspace request. A selected workspace is not authorization on its own.

Sessions are hashed in storage, expire, and are revoked on logout or password reset. This release uses operator-provisioned accounts, not an email-based signup or password reset service.

## Resources

| Resource | Operations |
| :--- | :--- |
| `/api/v1/projects` | List and create tenant projects |
| `/api/v1/workflows` | List and create workflows |
| `/api/v1/workflows/{id}` | Read a draft and its versions; update using expected revision |
| `/api/v1/workflows/{id}/publish` | Publish an immutable snapshot |
| `/api/v1/workflows/{id}/activate` | Choose a previously published version for new runs |
| `/api/v1/workflows/{id}/runs` | Submit an input using an Idempotency-Key header |
| `/api/v1/runs` | Paginated history with status and workflow filters |
| `/api/v1/runs/{id}` | State, inputs, step outputs, attempts and provider usage |
| `/api/v1/runs/{id}/cancel` | Stop committing new progress; does not undo external actions |
| `/api/v1/runs/{id}/replay` | New execution of the original version, with explicit live acknowledgment |
| `/api/v1/runs/{id}/steps/{node}/approval` | Approve or reject a pending review |
| `/api/v1/credentials` | List metadata and create encrypted credentials |
| `/api/v1/credentials/{id}/rotate` | Add a credential revision |
| `/api/v1/credentials/{id}/revoke` | Block future use of all revisions |
| `/api/v1/workspace`, `/api/v1/members` | Inspect and administer membership |
| `/api/v1/overview` | Actual installation metrics |

List endpoints use bounded `limit` and `offset`; do not assume cursor pagination. Generated OpenAPI has the exact fields and status codes. Errors use `error.code` and `error.detail`, with a request ID when available. Validation responses identify field paths without echoing supplied secrets.

## Signed inbound events

Send JSON to `/api/v1/hooks/{workflow_id}`. Set `X-FlowPilot-Timestamp` to Unix seconds and `X-FlowPilot-Event-ID` to a stable event identity. Compute the signature over:

```text
timestamp + "." + event_id + "." + raw_body_bytes
```

Use HMAC SHA-256 with the workflow signing secret and send `X-FlowPilot-Signature: sha256=<hex digest>`. The default clock tolerance is five minutes. Sign the exact bytes sent, not a reserialized version of the body.

A new event returns 202; a retained duplicate returns 200 with the same execution ID. Reusing the key with different valid input returns 409. The signing key is shown once on creation or rotation, never on a normal read.

A helper is included:

```bash
python scripts/send_webhook.py WORKFLOW_ID examples/event-input.json
```

Set `FLOWPILOT_WEBHOOK_SECRET` locally. The helper submits only to a loopback development server; it is not a general outbound automation tool.

## Diagnostics

`/health/live` checks the HTTP process. `/health/ready` checks database access and migration revision. Neither asserts that a worker is currently available. Inspect workspace heartbeats separately.

`/metrics` requires `Authorization: Bearer <FLOWPILOT_METRICS_TOKEN>`. Do not expose it publicly without access controls. Metric labels are bounded status values, not workflow IDs or arbitrary customer input.
