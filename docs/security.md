# Security model

This is a documented threat model and a set of tested controls, not a penetration-test certificate. Run the outstanding deployment checks before using real customer data.

## Trust boundaries

The browser is untrusted. A logged-in user can still target another workspace, submit an invalid workflow or attempt to leak a credential. Webhook senders and external AI/HTTP responses are untrusted. Application operators, database administrators and processes holding master keys are privileged.

Organization members share workflow inputs and redacted outputs within their workspace. Projects organize work and constrain credential references; they are not independent permission domains in this version.

## Controls

| Threat | Control and evidence |
| :--- | :--- |
| Cross-tenant access | Scoped resource queries, membership checks and tests for workflow/run/mutation boundaries |
| Session theft from storage | Random opaque tokens stored as hashes; HttpOnly cookies; expiry and revocation |
| CSRF | SameSite cookies, Origin checks and server-validated CSRF tokens |
| Password guessing | Argon2id and shared fixed-window limits for email and IP |
| Duplicate admission | Transactional idempotency records and uniqueness constraints |
| Stale worker results | Lease token and expiry checked before committing progress |
| Stored secret exposure | AES-GCM envelope encryption with resource-bound additional data |
| SSRF | Operator host allowlist, HTTPS only, public DNS answers, IP-pinned connection and no redirects |
| Unbounded external output | Timeouts, response-size limits and rejection of compressed responses |
| Workflow code execution | Fixed node types and bounded reference resolution; no eval or arbitrary plugins |
| Browser injection | Text-node rendering for data; fixed checked-in SVG paths; CSP and anti-framing headers |
| Error/log disclosure | Stable errors, no request-body logging, field-name and known-secret redaction |

## Credential handling

Each encrypted value uses a fresh data key; a configured master key wraps that data key. AAD binds ciphertext to the organization, resource identity and revision. Rewrapping supports master-key rotation without changing stored plaintext values.

The master keys live outside the database and must not enter source control. This is local key management, not a managed KMS/HSM. A process compromise that obtains both database access and master keys can decrypt values. Backups require protected key material too.

Credential values are never returned by credential endpoints. Execution output redaction is a best-effort display control. Encoded, transformed or partly exposed secrets may escape exact-match redaction. It is not data-loss prevention. Operators must decide which data may enter prompts or third-party services.

## Egress limitations

DNS answers are checked before connection. The socket connects to the vetted numeric address while TLS validates the original hostname, reducing a DNS-rebinding window. All resolved addresses must be public. Redirects are not followed. HTTP credentials are bound to one exact host.

A host allowlist is not a substitute for network policy. Block private ranges and metadata endpoints at the network layer as well. DNS resolution is not given a separately bounded asynchronous deadline. TLS/network behavior was checked with deterministic transport tests; live internet traffic is not part of the deterministic transport test suite.

An allowed host may still expose sensitive paths. Do not allow general-purpose proxies or internal administrative APIs. The operator, not a model, decides the allowed destinations.

## AI boundary

Model output is data. It cannot choose a new URL, unlock a credential, install a tool or execute code by itself. Schema validation checks structure, not truthfulness or business suitability. An attacker can still influence a classification or generated answer through prompt content. Place an approval step before sensitive downstream side effects.

## Deployment requirements

Use HTTPS and secure cookies, correct trusted hosts and origin, a supported PostgreSQL installation, restricted database credentials, process supervision, egress controls, encrypted backups and a tested restore. Production mode rejects SQLite, insecure cookies, non-HTTPS origin and missing metrics credentials.

No signup, MFA, SSO, OAuth provider lifecycle, automated abuse intelligence or independently reviewed sandbox is implemented. The application should not be sold as having those controls.

## Remaining review

The most important unverified area is concurrent PostgreSQL behavior under failure. Container startup, backup restore, native browser HTTP behavior, provider authentication and dependency-advisory scanning also require validation in the target deployment environment. See [verification](../verification/REPORT.md).
