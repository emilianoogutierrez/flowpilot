import pytest

from flowpilot.engine.definition import AiNode
from flowpilot.errors import ExecutionError
from flowpilot.integrations.ai import AiRuntime
from flowpilot.integrations.http import HttpResult


class ProviderTransport:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def request(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body, timeout))
        return HttpResult(200, self.body, {})


@pytest.mark.parametrize('provider,response,expected_input', [
    ('openai', {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}, 10),
    ('anthropic', {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"ok":true}'}], 'usage': {'input_tokens': 10, 'cache_read_input_tokens': 20, 'cache_creation_input_tokens': 30, 'output_tokens': 5}}, 60),
    ('gemini', {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"ok":true}'}]}}], 'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5}}, 10),
])
def test_provider_contracts(provider, response, expected_input):
    transport = ProviderTransport(response)
    node = AiNode(id='ai', type='ai', provider=provider, model='test-model', credential_id='test-key', prompt='classify', response_schema={'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']})
    result = AiRuntime(transport).execute(node, 'hello', 'secret-value', False)
    assert result.data == {'ok': True}
    assert result.usage['input_tokens'] == expected_input
    assert result.usage['output_tokens'] == 5
    assert result.usage['cost_usd'] is None
    assert not result.usage['simulated']
    assert 'secret-value' not in transport.calls[0][1]
    assert 'secret-value' not in str(transport.calls[0][3])


def test_fixture_never_makes_network_request():
    transport = ProviderTransport(None)
    node = AiNode(id='ai', type='ai', provider='mock', prompt='anything', mock_response={'ok': True})
    result = AiRuntime(transport).execute(node, 'anything', None, False)
    assert result.data == {'ok': True}
    assert result.usage['simulated'] is True
    assert result.usage['input_tokens'] is None
    assert transport.calls == []


def test_dry_run_uses_fixture_even_for_live_provider():
    node = AiNode(id='ai', type='ai', provider='openai', credential_id='x', model='x', prompt='anything')
    transport = ProviderTransport(None)
    assert AiRuntime(transport).execute(node, 'hello', None, True).usage['simulated']
    assert not transport.calls


def test_schema_mismatch_is_not_silently_accepted():
    node = AiNode(id='ai', type='ai', provider='mock', prompt='hello', mock_response={'ok': 'not a bool'}, response_schema={'type': 'object', 'properties': {'ok': {'type': 'boolean'}}})
    with pytest.raises(ExecutionError, match='ai_schema_mismatch'):
        AiRuntime(ProviderTransport(None)).execute(node, 'hello', None, False)


def test_truncated_response_is_not_a_success():
    node = AiNode(id='ai', type='ai', provider='openai', prompt='hello', model='test', credential_id='x')
    transport = ProviderTransport({'choices': [{'finish_reason': 'length', 'message': {'content': 'truncated'}}]})
    with pytest.raises(ExecutionError, match='ai_incomplete_output'):
        AiRuntime(transport).execute(node, 'hello', 'key', False)
