# 0001 Database-backed execution

Status: accepted.

## Context

A separate Redis queue would introduce an admission problem: the API can commit an execution but fail to publish its message, or publish before a rollback. An outbox could solve it, but is unnecessary for the current execution model and expected workload.

## Decision

Keep admission, due times, attempts, leases and execution state in the same relational database. PostgreSQL workers use row locking with SKIP LOCKED. SQLite provides a local mode with serialized writes, not equivalent concurrency guarantees.

## Consequences

There is one durable authority and fewer infrastructure components. Polling costs database work and limits throughput. State transitions require short transactions, appropriate indexes and a measured polling interval. A broker or separate dispatcher should only be introduced with a documented bottleneck and delivery contract.
