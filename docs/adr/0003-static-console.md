# 0003 Static TypeScript console

Status: accepted.

## Context

The console is operational tooling rather than the primary execution runtime. It needs a small dependency surface, predictable builds and the ability to ship with the Python service for local installations.

## Decision

Use strict TypeScript, native DOM construction and plain CSS. Serve the compiled console from the API, include the build output in releases and retain a reproducible TypeScript build from checked-in source.

## Consequences

The application can run without Node or a frontend CDN after installation. Forms, rendering and routing remain explicit and require direct tests. A future framework-based client can reuse the API contract without changing the execution engine.
