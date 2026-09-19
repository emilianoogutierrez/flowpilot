# Changelog

## Unreleased

Fixed scheduler fairness so workflows already at their concurrency limit cannot occupy the entire claim window.

Hardened lease timing by using the database clock for durable execution timestamps and enforcing a safety margin between external step timeouts and worker leases.

Improved execution error classification so invalid workflow inputs remain distinguishable from internal implementation failures.

## 0.1.0

Initial release with versioned workflow definitions, database-backed execution, signed webhooks, approval and delay nodes, credential encryption, three AI API adapters and a TypeScript operator console.

The release includes SQLite behavior tests, provider contract fixtures, transport-security tests, browser/API interaction checks, migration checks and a local benchmark. PostgreSQL, container and live-provider verification are tracked separately rather than reported as passed.
