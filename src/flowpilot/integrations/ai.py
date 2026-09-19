import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from jsonschema import Draft202012Validator

from flowpilot.engine.definition import AiNode
from flowpilot.errors import ExecutionError
from flowpilot.integrations.http import HttpTransport, require_success

PROVIDER_HOSTS = {"openai": "api.openai.com", "anthropic": "api.anthropic.com", "gemini": "generativelanguage.googleapis.com"}


@dataclass(frozen=True)
class NodeResult:
    data: Any
    usage: dict[str, Any] = field(default_factory=dict)


class AiRuntime:
    def __init__(self, transport: HttpTransport):
        self.transport = transport

    def execute(self, node: AiNode, prompt: Any, key: str | None, dry_run: bool) -> NodeResult:
        if dry_run or node.provider == "mock":
            data = node.mock_response
            self._validate_output(node, data)
            return NodeResult(data, {"provider": "mock", "model": "fixture", "simulated": True, "input_tokens": None, "output_tokens": None, "cost_usd": None})
        if not key:
            raise ExecutionError("credential_unavailable")
        text = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
        if len(text.encode()) > 32768:
            raise ExecutionError("ai_input_too_large")
        if node.response_schema:
            text += "\nReturn only JSON matching this schema:\n" + json.dumps(node.response_schema)
        headers: dict[str, str]
        if node.provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}"}
            body = {"model": node.model, "messages": [{"role": "user", "content": text}], "max_completion_tokens": node.max_output_tokens, "store": False}
            if node.response_schema:
                body["response_format"] = {"type": "json_object"}
        elif node.provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            body = {"model": node.model, "max_tokens": node.max_output_tokens, "messages": [{"role": "user", "content": text}]}
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(node.model, safe='')}:generateContent"
            headers = {"x-goog-api-key": key}
            generation: dict[str, Any] = {"maxOutputTokens": node.max_output_tokens}
            if node.response_schema:
                generation.update(responseMimeType="application/json", responseJsonSchema=node.response_schema)
            body = {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": generation}
        result = self.transport.request("POST", url, headers, body, node.timeout_seconds)
        require_success(result)
        try:
            if node.provider == "openai":
                choice = result.body["choices"][0]
                if choice.get("finish_reason") not in (None, "stop"):
                    raise ExecutionError("ai_incomplete_output")
                answer = choice["message"]["content"]
                usage = result.body.get("usage", {})
                input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
            elif node.provider == "anthropic":
                if result.body.get("stop_reason") not in (None, "end_turn", "stop_sequence"):
                    raise ExecutionError("ai_incomplete_output")
                answer = "".join(block["text"] for block in result.body["content"] if block["type"] == "text")
                usage = result.body.get("usage", {})
                input_tokens = sum(usage.get(field, 0) for field in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")) if "input_tokens" in usage else None
                output_tokens = usage.get("output_tokens")
            else:
                candidate = result.body["candidates"][0]
                if candidate.get("finishReason") not in (None, "STOP"):
                    raise ExecutionError("ai_incomplete_output")
                answer = "".join(part.get("text", "") for part in candidate["content"]["parts"] if not part.get("thought"))
                usage = result.body.get("usageMetadata", {})
                input_tokens = usage.get("promptTokenCount")
                output_tokens = usage.get("candidatesTokenCount")
            data = json.loads(answer) if node.response_schema else {"text": answer}
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ExecutionError("ai_response_invalid") from error
        self._validate_output(node, data)
        return NodeResult(data, {"provider": node.provider, "model": node.model, "simulated": False, "input_tokens": input_tokens, "output_tokens": output_tokens, "reported_usage": usage, "cost_usd": None})

    @staticmethod
    def _validate_output(node: AiNode, data: Any):
        if node.response_schema and not Draft202012Validator(node.response_schema).is_valid(data):
            raise ExecutionError("ai_schema_mismatch")
