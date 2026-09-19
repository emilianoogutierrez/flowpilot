import hmac

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flowpilot.api.app import create_app
from flowpilot.cli import create_user
from flowpilot.models import AuthSession, CredentialVersion, Membership, Run


def test_readiness_and_security_headers(client):
    response = client.get('/health/ready')
    assert response.status_code == 200
    assert response.json()['database'] == 'sqlite'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


def test_session_cookie_is_httponly_and_no_plaintext_token_in_db(client, db):
    token = client.cookies['fp_session']
    with db.sessions() as session:
        record = session.scalar(select(AuthSession))
        assert record.token_hash != token
        assert len(record.token_hash) == 64
    assert client.get('/api/v1/auth/me').status_code == 200


def test_csrf_and_origin_protection(client, identity):
    client.headers.pop('x-csrf-token')
    assert client.post('/api/v1/projects', json={'name': 'x'}).status_code == 403
    client.headers['x-csrf-token'] = client.cookies['fp_csrf']
    assert client.post('/api/v1/projects', json={'name': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/v1/projects', json={'name': 'x'}, headers={'Origin': 'http://testserver'}).status_code == 201


def test_logout_invalidates_the_session(client):
    assert client.post('/api/v1/auth/logout').status_code == 204
    assert client.get('/api/v1/auth/me').status_code == 401


def test_bad_password_is_generic_and_rate_limited(settings, db, identity):
    with TestClient(create_app(settings, db)) as client:
        for _ in range(10):
            response = client.post('/api/v1/auth/login', json={'email': 'missing@example.test', 'password': 'wrong'})
            assert response.status_code == 401
            assert response.json()['error']['code'] == 'invalid_credentials'
        assert client.post('/api/v1/auth/login', json={'email': 'missing@example.test', 'password': 'wrong'}).status_code == 429


def test_validation_error_does_not_echo_secret(client, identity):
    response = client.post('/api/v1/credentials', json={'name': 'x', 'project_id': identity['project_id'], 'kind': 'bad', 'value': 'sensitive-secret-value'})
    assert response.status_code == 422
    assert 'sensitive-secret-value' not in response.text


def test_request_size_and_nesting_limits(client):
    response = client.post('/api/v1/auth/login', content=b'x' * 140000, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    response = client.post('/api/v1/auth/login', content=b'[' * 60 + b']' * 60, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_unknown_api_route_never_returns_the_spa(client):
    response = client.get('/api/v1/missing')
    assert response.status_code == 404
    assert 'text/html' not in response.headers['content-type']


def test_tenant_boundary_for_every_resource(client, db, identity, make_workflow, make_run):
    first = make_workflow()
    run_id = make_run(first['workflow_id'])
    other = create_user(db, 'other@example.test', 'Other', 'another long password', 'Other workspace')
    client.headers['x-workspace-id'] = other['org_id']
    assert client.get('/api/v1/workflows').status_code == 403
    with db.transaction() as session:
        session.add(Membership(org_id=other['org_id'], user_id=identity['user_id'], role='admin'))
    assert client.get(f"/api/v1/workflows/{first['workflow_id']}").status_code == 404
    assert client.get(f'/api/v1/runs/{run_id}').status_code == 404
    assert client.post(f'/api/v1/runs/{run_id}/cancel').status_code == 404
    assert client.get('/api/v1/workflows').json()['items'] == []
    assert client.get('/api/v1/runs').json()['items'] == []


def test_viewer_cannot_mutate(client, db, identity, make_workflow):
    workflow = make_workflow()
    with db.transaction() as session:
        session.get(Membership, (identity['org_id'], identity['user_id'])).role = 'viewer'
    assert client.get('/api/v1/workflows').status_code == 200
    assert client.post(f"/api/v1/workflows/{workflow['workflow_id']}/publish", json={'expected_revision': 1}).status_code == 403
    assert client.post('/api/v1/credentials', json={'name': 'x', 'project_id': identity['project_id'], 'kind': 'openai', 'value': 'long-enough-value'}).status_code == 403


def test_create_update_publish_and_stale_draft(client, identity):
    definition = {'nodes': [{'id': 'x', 'type': 'set', 'values': {'value': 1}}]}
    created = client.post('/api/v1/workflows', json={'project_id': identity['project_id'], 'name': 'My workflow', 'definition': definition})
    assert created.status_code == 201
    workflow_id = created.json()['id']
    assert created.json()['webhook_secret']
    assert 'webhook_secret' not in client.get(f'/api/v1/workflows/{workflow_id}').text
    assert client.patch(f'/api/v1/workflows/{workflow_id}', json={'definition': definition, 'expected_revision': 1}).status_code == 200
    assert client.patch(f'/api/v1/workflows/{workflow_id}', json={'definition': definition, 'expected_revision': 1}).status_code == 409
    assert client.post(f'/api/v1/workflows/{workflow_id}/publish', json={'expected_revision': 1}).status_code == 409
    assert client.post(f'/api/v1/workflows/{workflow_id}/publish', json={'expected_revision': 2}).status_code == 201


def test_idempotency_conflict_and_duplicate_return(client, make_workflow):
    workflow = make_workflow()
    url = f"/api/v1/workflows/{workflow['workflow_id']}/runs"
    first = client.post(url, json={'input': {'x': 1}}, headers={'Idempotency-Key': 'same-key'})
    second = client.post(url, json={'input': {'x': 1}}, headers={'Idempotency-Key': 'same-key'})
    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    assert client.post(url, json={'input': {'x': 2}}, headers={'Idempotency-Key': 'same-key'}).status_code == 409
    assert client.post(url, json={'input': {}}).status_code == 400


def signed_headers(secret, body, event_id='event-1', timestamp=None):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    value = hmac.new(secret.encode(), stamp.encode() + b'.' + event_id.encode() + b'.' + body, 'sha256').hexdigest()
    return {'Content-Type': 'application/json', 'X-FlowPilot-Timestamp': stamp, 'X-FlowPilot-Event-ID': event_id, 'X-FlowPilot-Signature': 'sha256=' + value}


def test_webhook_signature_replay_and_clock_window(client, make_workflow):
    workflow = make_workflow()
    body = b'{"x":1}'
    url = f"/api/v1/hooks/{workflow['workflow_id']}"
    headers = signed_headers(workflow['secret'], body)
    first = client.post(url, content=body, headers=headers)
    assert first.status_code == 202
    repeat = client.post(url, content=body, headers=headers)
    assert repeat.status_code == 200
    assert repeat.json()['duplicate'] is True
    assert repeat.json()['id'] == first.json()['id']
    assert client.post(url, content=b'{"x":2}', headers=headers).status_code == 401
    assert client.post(url, content=body, headers=signed_headers(workflow['secret'], body, timestamp=int(time.time()) - 400)).status_code == 401
    assert client.post(url, content=body, headers={**headers, 'X-FlowPilot-Event-ID': 'forged'}).status_code == 401


def test_webhook_rotation_invalidates_old_signature(client, make_workflow):
    workflow = make_workflow()
    body = b'{}'
    response = client.post(f"/api/v1/workflows/{workflow['workflow_id']}/rotate-webhook")
    assert response.status_code == 200
    url = f"/api/v1/hooks/{workflow['workflow_id']}"
    assert client.post(url, content=body, headers=signed_headers(workflow['secret'], body)).status_code == 401
    assert client.post(url, content=body, headers=signed_headers(response.json()['webhook_secret'], body)).status_code == 202


def test_replay_pins_original_version_and_requires_confirmation(client, make_workflow, make_run):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    assert client.post(f'/api/v1/runs/{run_id}/replay', json={'dry_run': False}).status_code == 422
    replay = client.post(f'/api/v1/runs/{run_id}/replay', json={'dry_run': True})
    assert replay.status_code == 202
    assert replay.json()['parent_id'] == run_id
    assert replay.json()['id'] != run_id


def test_credentials_are_encrypted_and_not_returned(client, db, identity):
    secret = 'a-very-specific-long-key'
    response = client.post('/api/v1/credentials', json={'project_id': identity['project_id'], 'name': 'Example', 'kind': 'openai', 'value': secret})
    assert response.status_code == 201
    assert secret not in response.text
    assert secret not in client.get('/api/v1/credentials').text
    with db.sessions() as session:
        assert secret not in session.scalar(select(CredentialVersion)).ciphertext
    credential_id = response.json()['id']
    assert client.post(f'/api/v1/credentials/{credential_id}/rotate', json={'value': 'second-very-long-key'}).json()['version'] == 2
    assert client.post(f'/api/v1/credentials/{credential_id}/revoke').json()['revoked'] is True
    assert client.post(f'/api/v1/credentials/{credential_id}/rotate', json={'value': 'third-very-long-key'}).status_code == 404


def test_input_is_encrypted_but_redacted_on_read(client, db, make_workflow, make_run):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'], {'password': 'top-private-value', 'message': 'hello'})
    detail = client.get(f'/api/v1/runs/{run_id}').json()
    assert detail['input']['password'] == '[redacted]'
    with db.sessions() as session:
        assert 'top-private-value' not in session.get(Run, run_id).input_cipher


def test_metrics_require_operator_token(client):
    assert client.get('/metrics').status_code == 401
    response = client.get('/metrics', headers={'Authorization': 'Bearer test-metrics-token-that-is-long-enough'})
    assert response.status_code == 200
    assert 'flowpilot_workers_active' in response.text


def test_overview_never_fabricates_success_rate(client):
    data = client.get('/api/v1/overview').json()
    assert data['total'] == 0
    assert data['success_rate'] is None
    assert all(day['total'] == 0 for day in data['activity'])


def test_role_changes_and_project_creation(client, db, identity):
    other = create_user(db, 'reader@example.test', 'Reader', 'another secure password')
    assert client.post('/api/v1/members', json={'email': 'reader@example.test', 'role': 'viewer'}).status_code == 200
    assert client.post('/api/v1/members', json={'email': 'owner@example.test', 'role': 'viewer'}).status_code == 409
    assert client.post('/api/v1/projects', json={'name': 'Another'}).status_code == 201
    assert len(client.get('/api/v1/projects').json()['items']) == 2
    assert len(client.get('/api/v1/workspace').json()['members']) == 2


def test_input_schema_is_enforced(client, make_workflow):
    workflow = make_workflow(input_schema={'type': 'object', 'properties': {'amount': {'type': 'integer', 'minimum': 1}}, 'required': ['amount']})
    response = client.post(f"/api/v1/workflows/{workflow['workflow_id']}/runs", json={'input': {'amount': 'bad'}}, headers={'Idempotency-Key': 'bad-input'})
    assert response.status_code == 422


def test_backpressure_is_enforced(client, settings, make_workflow):
    settings.max_queued_runs = 1
    workflow = make_workflow()
    url = f"/api/v1/workflows/{workflow['workflow_id']}/runs"
    assert client.post(url, json={'input': {}}, headers={'Idempotency-Key': 'one'}).status_code == 202
    assert client.post(url, json={'input': {}}, headers={'Idempotency-Key': 'two'}).status_code == 429


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_nonfinite_json_never_reaches_persistence(client, number):
    response = client.post('/api/v1/auth/login', content='{"value":' + number + '}', headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'invalid_json'
