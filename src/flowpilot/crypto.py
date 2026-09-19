import base64
import hashlib
import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Vault:
    def __init__(self, keys_json: str, active_id: str):
        self.keys = {key: base64.urlsafe_b64decode(value) for key, value in json.loads(keys_json).items()}
        self.active_id = active_id

    def seal(self, value: Any, context: str) -> str:
        data_key = AESGCM.generate_key(bit_length=256)
        nonce, wrap_nonce = os.urandom(12), os.urandom(12)
        aad = context.encode()
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        payload = AESGCM(data_key).encrypt(nonce, raw, aad)
        wrapped = AESGCM(self.keys[self.active_id]).encrypt(wrap_nonce, data_key, aad)
        return json.dumps({"v": 1, "key": self.active_id, "nonce": _encode(nonce), "payload": _encode(payload), "wrap_nonce": _encode(wrap_nonce), "wrapped": _encode(wrapped)})

    def open(self, ciphertext: str, context: str) -> Any:
        envelope = json.loads(ciphertext)
        if envelope["v"] != 1:
            raise ValueError("Unsupported encrypted envelope version")
        aad = context.encode()
        key = AESGCM(self.keys[envelope["key"]]).decrypt(_decode(envelope["wrap_nonce"]), _decode(envelope["wrapped"]), aad)
        raw = AESGCM(key).decrypt(_decode(envelope["nonce"]), _decode(envelope["payload"]), aad)
        return json.loads(raw)

    def rewrap(self, ciphertext: str, context: str) -> str:
        envelope = json.loads(ciphertext)
        aad = context.encode()
        data_key = AESGCM(self.keys[envelope["key"]]).decrypt(_decode(envelope["wrap_nonce"]), _decode(envelope["wrapped"]), aad)
        nonce = os.urandom(12)
        envelope.update(key=self.active_id, wrap_nonce=_encode(nonce), wrapped=_encode(AESGCM(self.keys[self.active_id]).encrypt(nonce, data_key, aad)))
        return json.dumps(envelope)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def json_digest(value: Any) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


SENSITIVE_KEY = re.compile(r"password|secret|token|authorization|api.?key|cookie|credential", re.I)


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if SENSITIVE_KEY.search(key) else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value
