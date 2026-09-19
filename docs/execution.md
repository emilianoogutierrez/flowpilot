# Execution semantics

## States

Runs move through `queued`, `running`, `waiting` and `retry_wait`. Terminal states are `succeeded`, `failed` and `cancelled`.

Steps add `pending`, `skipped` and `awaiting_approval`. The separate attempt table records actual invocations as `running`, `succeeded`, `failed` or `abandoned`.

## Claim, prepare, execute, commit

A worker claims a due run and stores a random lease token and expiry. PostgreSQL uses `FOR UPDATE SKIP LOCKED`; local SQLite serializes the write transaction. Claiming also checks the workflow's configured concurrency limit.

Preparation checks ownership, loads the immutable definition and persisted ancestor outputs, then either records a durable wait or creates a running attempt. The network request occurs after this transaction commits.

The result transaction accepts an output only if the same lease is still valid and the run is still running. Cancellation and an expired/replaced lease prevent a late worker from committing. This fence protects database state, not the external service from a request already sent.

## Failure windows

| Failure | Result |
| :--- | :--- |
| Before admission commit | No durable run exists; the sender can retry the same event |
| After admission, before claim | Another worker can claim the run |
| During a safe step | An expired lease allows recovery, subject to the attempt budget |
| During an unsafe HTTP step | Recovery marks `outcome_unknown` rather than blindly repeating the action |
| After external success, before result commit | The receiver may have acted; exactly-once execution is not guaranteed |
| After cancellation | In-flight external work may finish, but cannot overwrite cancelled state |
| Database unavailable | No acknowledgment of successful state persistence; the worker retries its loop later |

## Idempotency and retries

Incoming signed events and manual requests use explicit idempotency keys. Outbound HTTP actions receive a stable key derived from run and node identity. Repeated attempts of that step use the same key. A replay is a different run and therefore has different external side-effect keys.

GET requests can retry transient transport errors, HTTP 429 and HTTP 5xx. Other methods only retry when `receiver_supports_idempotency` is explicitly enabled. That flag is an operator assertion about the receiver; FlowPilot cannot make an arbitrary API honor it.

Backoff grows exponentially, is capped, and includes deterministic per-run jitter. A numeric Retry-After may increase the delay up to the transport cap. Retries persist a due time instead of sleeping while holding a lease.

AI calls can be repeated after an ambiguous network/worker failure and may incur duplicate provider charges. An AI-generated response is not necessarily reproducible. This release records provider usage but does not enforce a monetary budget.

## Versions and credentials

Runs keep the workflow version used at admission. Draft edits, later publication and activating an older version do not change existing run definitions.

Credential revisions are pinned when a run is admitted. Rotation affects new runs; existing runs keep their revision. Revocation prevents subsequent reads of that credential, including pinned revisions. It cannot retract a key already loaded into an in-flight request. Master-key rewrapping changes wrapping material, not the secret values.

A replay uses the original workflow definition and input but resolves current credential revisions. It does not claim to reproduce a past external system or model state.

## Waiting and branching

Delay nodes store a due timestamp. Approval nodes store a deadline and require an authorized operator. Rejection is terminal. Expired approvals fail on the next eligible worker pass.

Dependencies must be terminal before a node is evaluated. `join=all` skips a node when any parent is skipped; `join=any` only skips when all parents are skipped. A `when` predicate can further suppress a node. A failed executed step stops the run; this release does not offer continue-on-error branches.

## Inspecting uncertain work

Do not replay `outcome_unknown` automatically. First inspect the receiver using the external idempotency key or its business identifier. Record the result in the incident notes. Replay only after understanding whether the original action occurred.
