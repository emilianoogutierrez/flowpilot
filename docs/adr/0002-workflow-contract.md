# 0002 Narrow workflow contract

Status: accepted.

## Context

An arbitrary code node would turn the workflow engine into a multi-tenant code-execution service with a substantially different threat model.

## Decision

Provide six typed node kinds, bounded JSON references and declarative predicates. Definitions are validated before publication. Published snapshots are immutable at the API layer.

## Consequences

Users cannot execute arbitrary Python, JavaScript, regexes or templating expressions. More transformations will require deliberate node implementations. The smaller contract makes validation, failure behavior and review tractable.
