# Code tour

This document is a quick route through the parts of FlowPilot that define its execution semantics and security boundaries.

## Execution engine

Start with `src/flowpilot/engine/worker.py`. The main path is `claim`, `prepare`, `execute` and `finish`. External work happens outside database transactions, and a worker must still own a valid lease before committing the result.

`tests/test_worker.py` covers lease loss, duplicate claims, cancellation, retry behavior, approval waits, unsafe side effects and pinned credentials.

## API and tenant boundaries

`src/flowpilot/api/` owns authentication, CSRF/origin checks, permission enforcement and request validation. `tests/test_api.py` exercises tenant isolation, role boundaries, webhook signing and duplicate admission.

## Outbound HTTP

`src/flowpilot/integrations/http.py` owns destination validation, DNS/address checks, TLS hostname verification, bounded reads and redirect refusal. It is intentionally narrower than a general-purpose HTTP client.

## AI adapters

`src/flowpilot/integrations/ai.py` translates a small provider-neutral operation into provider-specific requests and validates the returned structure before it re-enters the workflow engine. Provider output is treated as untrusted data.

## Questions the implementation answers

| Question | Where to look |
| :--- | :--- |
| Can a stale worker overwrite newer progress? | Lease checks in the worker and fencing tests |
| What happens after a repeated webhook? | Transactional admission and idempotency tests |
| Can one tenant read another tenant's run? | Scoped lookups and cross-tenant API tests |
| Does credential rotation rewrite active runs? | Credential revision snapshots and rotation tests |
| What happens when an external request times out? | Safe/unsafe retry handling and persisted retry state |
| How are local verification claims bounded? | `verification/REPORT.md` |
