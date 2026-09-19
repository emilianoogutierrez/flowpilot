# Workflow contract

Definitions are JSON, validated by Pydantic and a bounded subset of JSON Schema 2020-12. The canonical generated schema is [workflow-schema.json](workflow-schema.json).

```json
{
  "schema_version": 1,
  "input_schema": {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": false
  },
  "nodes": [
    {
      "id": "normalize",
      "type": "set",
      "values": {"customer": {"$ref": "input.name"}}
    },
    {
      "id": "review",
      "type": "approval",
      "depends_on": ["normalize"],
      "message": "Approve the next operation."
    }
  ]
}
```

## Shared fields

| Field | Meaning |
| :--- | :--- |
| `id` | Unique lower-case identifier, up to 48 characters; numbers and underscores after the first letter |
| `label` | Optional display label |
| `depends_on` | Node IDs that must finish first |
| `join` | `all` or `any`, controlling skipped dependencies |
| `when` | Optional predicate over the input or ancestor outputs |
| `retry` | Attempts, initial backoff and capped backoff |
| `timeout_seconds` | External operation timeout, between 1 and 30 seconds |

A reference is an object containing exactly `$ref`. Paths start with `input` or `steps.<ancestor>`, then traverse object keys or numeric array indexes. This is not JavaScript, Python, Jinja or JSONPath evaluation. References to unrelated or future nodes fail compilation.

## Nodes

| Type | Specific fields | Output |
| :--- | :--- | :--- |
| `set` | `values` object with optional references | Resolved object |
| `condition` | `predicate` | `{ "match": true/false }` |
| `delay` | `seconds`, 1 to 604800 | Recorded wait duration |
| `approval` | `message`, optional `expires_after` | Decision, reviewer ID and review note |
| `http` | HTTPS URL, method, headers, body, optional credential ID and idempotency assertion | Status and bounded response body |
| `ai` | Provider, model, prompt, optional response schema, credential ID and output limit | Structured result or a text field |

Predicates support `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains` and `exists`. Both sides may contain references. Invalid type comparisons fail safely rather than becoming code execution.

## AI behavior

Use `provider=mock` for a deterministic, explicitly labeled fixture. `mock_response` is used by mock mode and dry runs. A live provider requires a matching credential kind. Model IDs are configuration supplied by the operator; consult that provider's current model documentation rather than copying an invented model name.

The three live adapters normalize a limited text/JSON generation operation. They do not promise full API parity or tool calling. The runtime validates responses locally; malformed, truncated or rejected outputs fail the step. Token counts are reported only when provided. Monetary cost remains unknown without a separate pricing model.

## Safety limits

Definitions, schemas, input bodies, output bodies, node counts, retry budgets and nesting depth are bounded. JSON Schema `$ref`, dynamic references, regex patterns and content schemas are deliberately rejected. This avoids remote schema retrieval and an unbounded regex execution surface in submitted definitions.

HTTP URLs are literal, not templated from input. Secret headers are reserved. An administrator binds HTTP credentials to an approved host, while the deployment also needs that host in `FLOWPILOT_EGRESS_HOSTS`. Redirects, private addresses and compressed responses are rejected by the restricted transport.

## Examples

[Lead triage](../examples/lead-triage.json) demonstrates references, a budget predicate, mock AI, approval and a handoff payload. It does not secretly send email or create a CRM record.

[Event normalization](../examples/normalize-event.json) demonstrates schema validation and conditional mapping without external dependencies.

[Reviewed delivery](../examples/http-delivery.json) is an outbound template that stays unpublished in the seeded workspace. Configure a real host and receiver before publishing. It does not assume that example.com implements your business operation.

Validate a file without starting the server:

```bash
python -m flowpilot.cli validate examples/lead-triage.json
```
