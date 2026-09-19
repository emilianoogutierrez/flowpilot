import base64
import json
import os

import pytest
from cryptography.exceptions import InvalidTag

from flowpilot.crypto import Vault, digest, json_digest, redact


def test_ciphertext_hides_values_and_is_randomized(vault):
    value = {"private": "very-secret-value"}
    first, second = vault.seal(value, 'tenant:a'), vault.seal(value, 'tenant:a')
    assert 'very-secret-value' not in first
    assert first != second
    assert vault.open(first, 'tenant:a') == value


def test_authenticated_context_blocks_tenant_swap(vault):
    ciphertext = vault.seal('a key', 'tenant:a')
    with pytest.raises(InvalidTag):
        vault.open(ciphertext, 'tenant:b')


def test_rotation_rewraps_without_changing_payload(settings, vault):
    keys = json.loads(settings.master_keys.get_secret_value())
    keys['v2'] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    rotated = Vault(json.dumps(keys), 'v2')
    original = vault.seal({'x': 1}, 'x')
    new = rotated.rewrap(original, 'x')
    assert json.loads(new)['payload'] == json.loads(original)['payload']
    assert rotated.open(new, 'x') == {'x': 1}
    assert json.loads(new)['key'] == 'v2'


def test_redaction_covers_nested_keys_and_literal_secrets():
    assert redact({'password': 'bad', 'items': [{'hello': 'prefix demo-secret-value suffix'}]}, ('demo-secret-value',)) == {'password': '[redacted]', 'items': [{'hello': 'prefix [redacted] suffix'}]}


def test_hash_is_stable_and_not_plaintext():
    assert digest('x') != 'x'
    assert json_digest({'a': 1, 'b': 2}) == json_digest({'b': 2, 'a': 1})
