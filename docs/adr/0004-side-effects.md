# 0004 Explicit side effects

Status: accepted.

## Context

A process may send an external request successfully and die before persisting the response. A queue cannot independently guarantee exactly-once behavior at the remote service.

## Decision

Fence database commits with leased tokens, use stable per-run/node idempotency keys, retry unsafe HTTP methods only when receiver support is declared, and stop uncertain unsafe requests for operator review. Replays have new execution identities and require explicit acknowledgment for live side effects.

## Consequences

Operators must understand receiver semantics. Some recoveries stop instead of automatically completing. AI requests can still be billed twice after ambiguous failures. This is a documented tradeoff, not an exactly-once claim.
