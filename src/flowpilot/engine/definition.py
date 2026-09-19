import json
import re
from collections import deque
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from flowpilot.limits import MAX_NODE_TIMEOUT_SECONDS

NODE_NAME = r"^[a-z][a-z0-9_]{0,47}$"
REFERENCE = re.compile(r"^(input|steps)(\.[A-Za-z0-9_]+)+$")
FORBIDDEN_SCHEMA_KEYS = {"$ref", "$dynamicRef", "pattern", "patternProperties", "contentSchema"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=3, ge=1, le=5)
    initial_seconds: float = Field(default=1, ge=0.1, le=30)
    max_seconds: float = Field(default=60, ge=1, le=300)


class Predicate(StrictModel):
    left: Any
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists"] = "eq"
    right: Any = None


class NodeBase(StrictModel):
    id: str = Field(pattern=NODE_NAME)
    label: str = Field(default="", max_length=80)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    join: Literal["all", "any"] = "all"
    when: Predicate | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: int = Field(default=15, ge=1, le=MAX_NODE_TIMEOUT_SECONDS)


class SetNode(NodeBase):
    type: Literal["set"]
    values: dict[str, Any]


class ConditionNode(NodeBase):
    type: Literal["condition"]
    predicate: Predicate


class DelayNode(NodeBase):
    type: Literal["delay"]
    seconds: int = Field(ge=1, le=604800)


class ApprovalNode(NodeBase):
    type: Literal["approval"]
    message: str = Field(min_length=1, max_length=300)
    expires_after: int = Field(default=86400, ge=60, le=604800)


class HttpNode(NodeBase):
    type: Literal["http"]
    url: str = Field(min_length=9, max_length=2048)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    credential_id: str | None = None
    receiver_supports_idempotency: bool = False

    @model_validator(mode="after")
    def validate_headers(self) -> "HttpNode":
        reserved = {"authorization", "proxy-authorization", "host", "cookie", "content-length", "connection", "transfer-encoding", "idempotency-key"}
        for key, value in self.headers.items():
            if key.lower() in reserved or "\r" in value or "\n" in value or not re.fullmatch(r"[A-Za-z0-9-]+", key):
                raise ValueError("Reserved or invalid HTTP header")
        if len(self.headers) > 12:
            raise ValueError("At most 12 custom headers are supported")
        return self


class AiNode(NodeBase):
    type: Literal["ai"]
    provider: Literal["mock", "openai", "anthropic", "gemini"]
    model: str = Field(default="fixture", max_length=100, pattern=r"^[A-Za-z0-9._:/-]+$")
    prompt: Any
    credential_id: str | None = None
    response_schema: dict[str, Any] | None = None
    mock_response: Any = Field(default_factory=lambda: {"category": "support", "priority": "normal"})
    max_output_tokens: int = Field(default=512, ge=16, le=2048)

    @model_validator(mode="after")
    def validate_provider(self) -> "AiNode":
        if self.provider != "mock" and not self.credential_id:
            raise ValueError("A live AI provider requires a credential")
        if self.response_schema:
            validate_json_schema(self.response_schema)
        return self


Node = Annotated[SetNode | ConditionNode | DelayNode | ApprovalNode | HttpNode | AiNode, Field(discriminator="type")]


class Definition(StrictModel):
    schema_version: Literal[1] = 1
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    nodes: list[Node] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def compile(self) -> "Definition":
        if len(json.dumps(self.model_dump()).encode()) > 65536:
            raise ValueError("Workflow definitions are limited to 64 KiB")
        validate_json_schema(self.input_schema)
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Node identifiers must be unique")
        for node in self.nodes:
            if len(set(node.depends_on)) != len(node.depends_on):
                raise ValueError(f"Duplicate dependency in {node.id}")
            if node.id in node.depends_on or set(node.depends_on) - by_id.keys():
                raise ValueError(f"Unknown or self dependency in {node.id}")
        order = topological_order(self.nodes)
        ancestors: dict[str, set[str]] = {}
        for node in order:
            ancestors[node.id] = set(node.depends_on)
            for parent in node.depends_on:
                ancestors[node.id].update(ancestors[parent])
            for reference in references(node.model_dump()):
                if not REFERENCE.fullmatch(reference):
                    raise ValueError(f"Invalid reference: {reference}")
                parts = reference.split(".")
                if parts[0] == "steps" and (len(parts) < 3 or parts[1] not in ancestors[node.id]):
                    raise ValueError(f"{node.id} may only reference ancestor outputs")
        return self


def validate_json_schema(schema: dict) -> None:
    if len(json.dumps(schema)) > 12000:
        raise ValueError("JSON Schema is too large")
    queue = deque([(schema, 0)])
    while queue:
        item, depth = queue.popleft()
        if depth > 12:
            raise ValueError("JSON Schema is too deeply nested")
        if isinstance(item, dict):
            if FORBIDDEN_SCHEMA_KEYS.intersection(item):
                raise ValueError("Remote references and regex schemas are not supported")
            queue.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            queue.extend((value, depth + 1) for value in item)
    Draft202012Validator.check_schema(schema)


def topological_order(nodes: list[Node]) -> list[Node]:
    remaining = {node.id: set(node.depends_on) for node in nodes}
    by_id = {node.id: node for node in nodes}
    result = []
    while remaining:
        ready = [key for key, value in remaining.items() if not value]
        if not ready:
            raise ValueError("Workflows must be acyclic")
        for key in ready:
            result.append(by_id[key])
            del remaining[key]
        for parents in remaining.values():
            parents.difference_update(ready)
    return result


def references(value: Any):
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("References must contain exactly one string $ref")
            yield value["$ref"]
        else:
            for item in value.values():
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def resolve(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            result: Any = context
            for key in value["$ref"].split("."):
                if isinstance(result, dict) and key in result:
                    result = result[key]
                elif isinstance(result, list) and key.isdigit() and int(key) < len(result):
                    result = result[int(key)]
                else:
                    raise ValueError(f"Missing reference: {value['$ref']}")
            return result
        return {key: resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, context) for item in value]
    return value


def evaluate(predicate: Predicate, context: dict) -> bool:
    try:
        left = resolve(predicate.left, context)
    except ValueError:
        if predicate.op == "exists":
            return False
        raise
    right = resolve(predicate.right, context)
    match predicate.op:
        case "exists":
            return left is not None
        case "eq":
            return left == right
        case "ne":
            return left != right
        case "gt":
            return left > right
        case "gte":
            return left >= right
        case "lt":
            return left < right
        case "lte":
            return left <= right
        case "contains":
            return right in left
    raise ValueError("Unsupported predicate")
