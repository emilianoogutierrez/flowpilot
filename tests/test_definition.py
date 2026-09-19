import pytest
from pydantic import ValidationError

from flowpilot.engine.definition import (
    Definition,
    Predicate,
    evaluate,
    resolve,
    topological_order,
    validate_json_schema,
)


def test_topological_order_is_stable():
    value = Definition.model_validate({"nodes": [
        {"id": "last", "type": "set", "values": {}, "depends_on": ["first"]},
        {"id": "first", "type": "set", "values": {}},
    ]})
    assert [node.id for node in topological_order(value.nodes)] == ['first', 'last']


@pytest.mark.parametrize('nodes', [
    [],
    [{"id": "x", "type": "set", "values": {}, "depends_on": ["x"]}],
    [{"id": "x", "type": "set", "values": {}, "depends_on": ["missing"]}],
    [{"id": "x", "type": "set", "values": {}}, {"id": "x", "type": "set", "values": {}}],
    [{"id": "x", "type": "set", "values": {}, "depends_on": ["y"]}, {"id": "y", "type": "set", "values": {}, "depends_on": ["x"]}],
    [{"id": "x", "type": "python", "code": "print('unsafe')"}],
    [{"id": "x", "type": "set", "values": {"x": {"$ref": "env.TOKEN"}}}],
    [{"id": "x", "type": "set", "values": {"x": {"$ref": "steps.y.value"}}}],
    [{"id": "x", "type": "set", "values": {"x": {"$ref": "input.name", "another": True}}}],
    [{"id": "x", "type": "set", "values": {}, "unexpected": True}],
])
def test_invalid_graphs_rejected(nodes):
    with pytest.raises((ValidationError, ValueError)):
        Definition.model_validate({"nodes": nodes})


def test_only_ancestor_outputs_can_be_referenced():
    with pytest.raises(ValidationError):
        Definition.model_validate({"nodes": [
            {"id": "a", "type": "set", "values": {"x": 4}},
            {"id": "b", "type": "set", "values": {"x": {"$ref": "steps.a.x"}}},
        ]})


def test_references_preserve_json_types():
    context = {"input": {"nested": [{"value": 9}], "flag": False}, "steps": {}}
    assert resolve({"a": {"$ref": "input.nested.0.value"}, "b": [{"$ref": "input.flag"}]}, context) == {"a": 9, "b": [False]}
    with pytest.raises(ValueError):
        resolve({"$ref": "input.nested.99.value"}, context)


@pytest.mark.parametrize('op,left,right,expected', [
    ('eq', 4, 4, True), ('ne', 4, 4, False), ('gt', 4, 3, True),
    ('gte', 4, 4, True), ('lt', 4, 3, False), ('lte', 4, 4, True),
    ('contains', ['x', 'y'], 'y', True), ('exists', 0, None, True),
    ('exists', None, None, False),
])
def test_predicates(op, left, right, expected):
    assert evaluate(Predicate(left=left, op=op, right=right), {}) == expected


def test_exists_handles_missing_reference():
    assert not evaluate(Predicate(left={"$ref": "input.missing"}, op="exists"), {"input": {}})


@pytest.mark.parametrize('schema', [{"$ref": "https://evil.example/schema"}, {"pattern": "(a+)+$"}, {"type": "nonexistent"}])
def test_unbounded_schema_features_rejected(schema):
    with pytest.raises(Exception):
        validate_json_schema(schema)


def test_deep_schema_rejected():
    schema = {}
    for _ in range(20):
        schema = {"type": "object", "properties": {"value": schema}}
    with pytest.raises(ValueError):
        validate_json_schema(schema)


@pytest.mark.parametrize('header', ['Authorization', 'Host', 'Cookie', 'Idempotency-Key', 'x\r\ninjected'])
def test_reserved_http_headers_rejected(header):
    with pytest.raises(ValidationError):
        Definition.model_validate({"nodes": [{"id": "http", "type": "http", "url": "https://api.example.com", "headers": {header: "value"}}]})


def test_live_ai_requires_credential():
    with pytest.raises(ValidationError):
        Definition.model_validate({"nodes": [{"id": "ai", "type": "ai", "provider": "anthropic", "model": "test", "prompt": "test"}]})
