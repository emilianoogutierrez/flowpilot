# Architecture

FlowPilot is a modular application with two process roles: the HTTP control plane and execution workers. They share a relational database, not process memory. The browser is a replaceable client of the HTTP API.

## Why these boundaries

The API authenticates callers, enforces workspace permissions, validates definitions and commits operator decisions. It does not execute remote workflow actions in a request handler.

A worker acquires a time-limited claim, prepares a step transactionally, performs its external work outside the database transaction and attempts a fenced commit. The transport owns destination policy and bounded response handling. Provider adapters only translate a limited common AI operation into each provider's request and response format.

Database transactions, not a broker acknowledgment, decide whether work exists. This avoids a database/Redis dual-write window in the first release. PostgreSQL row locks support multiple process instances; SQLite uses `BEGIN IMMEDIATE` for local write serialization. The two modes must not be assumed to have identical concurrency behavior.

## Data model

| Record | Role |
| :--- | :--- |
| User, AuthSession | Identity and revocable hashed sessions |
| Organization, Membership | Tenant identity and owner/admin/developer/viewer roles |
| Project | Group of workflows and credentials inside a tenant |
| Workflow | Mutable draft, revision and current published version |
| WorkflowVersion | Immutable definition snapshot and digest |
| Run | Version, encrypted input, pinned credentials, state, lease and correlation ID |
| StepRun | Current durable state and encrypted output for one node |
| Attempt | Each actual invocation, including abandoned attempts |
| Credential, CredentialVersion | Stable identity and encrypted secret revisions |
| AuditEvent | Application-recorded configuration and operator actions |
| RateBucket, WorkerHeartbeat | Shared request counters and observed worker liveness |

Foreign keys and unique constraints protect relationships and duplicate admission. Tenant isolation is application enforced, with tests against cross-tenant resource access. This version does not implement database row-level security or protection against a privileged database operator.

## Admission transaction

The API locks the workflow, resolves the requested published version and checks idempotency. A repeated key with identical input returns the existing run; changing the input produces a conflict. Admission also locks the organization before counting outstanding runs. The run, its encrypted input, pinned credential versions, initial steps and audit record commit together.

An idempotency key is scoped to an organization and workflow. Its lifetime is the retained run's lifetime. Purging historical runs also ends the corresponding duplicate-detection record.

## Runtime limits

Definitions contain at most 32 nodes and 64 KiB. Execution inputs are limited to 64 KiB. External calls have bounded request and response sizes. A step's external timeout is at most 30 seconds. The default lease is 90 seconds. DNS lookup and database stalls are not a universal hard wall-clock deadline; use process/network controls for deployment.

The workflow concurrency setting limits in-flight leased runs for that workflow. A single run executes one actionable node at a time, even when the graph exposes independent branches. Delays and approvals release their lease; they do not consume an idle worker.

## Browser console

Strict TypeScript modules render native DOM elements. User-controlled strings become text nodes, not HTML. Only checked-in icon paths use SVG markup. The console has no client-side authentication token store; the server uses an HttpOnly session cookie and a separate CSRF value. Workspace selection is a non-secret session preference.

The generated files in `web/dist` allow the local demonstration to run without a Node toolchain. `npm run build` regenerates them from the TypeScript source.

## Deliberate exclusions

The application is not a general code sandbox, payment processor, identity provider or hosted automation marketplace. AI output cannot install tools or grant itself credentials. There is no arbitrary Python/JavaScript evaluation, implicit provider fallback, streaming AI output, billing, enterprise SSO or database-per-tenant provisioning.

The current breadth is bounded by tested execution behavior. Adding integrations should reuse the transport boundary rather than introduce a second unrestricted HTTP client.
