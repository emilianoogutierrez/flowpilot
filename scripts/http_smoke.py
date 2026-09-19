"""Exercise the installed API, static files and a separate worker over loopback HTTP."""
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import httpx

from browser_smoke import local_server
from flowpilot.cli import create_user, migrate
from flowpilot.config import Settings
from flowpilot.db import Database


def main():
    checks = []
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            base_url = f'http://127.0.0.1:{probe.getsockname()[1]}'
        settings = Settings(environment='test', database_url=f'sqlite:///{directory / "http.db"}', master_keys=json.dumps({'v1': base64.urlsafe_b64encode(os.urandom(32)).decode()}), public_origin=base_url, allowed_hosts=['127.0.0.1'], static_dir=ROOT / 'web/dist')
        migrate(settings.database_url)
        db = Database(settings.database_url)
        password = secrets.token_urlsafe(24)
        identity = create_user(db, 'http@example.test', 'HTTP test', password, 'HTTP test workspace')
        with local_server(settings, directory, base_url), httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
            response = client.get('/health/ready')
            assert response.status_code == 200
            checks.append('API process boots and migration readiness succeeds')
            assert client.get('/').status_code == 200
            assert 'text/html' in client.get('/').headers['content-type']
            assert client.get('/assets/app.js').status_code == 200
            assert client.get('/styles.css').status_code == 200
            checks.append('HTML, compiled modules and CSS are served over HTTP')
            schema = client.get('/api/openapi.json')
            assert schema.status_code == 200
            assert '/api/v1/workflows' in schema.json()['paths']
            checks.append('OpenAPI is available without external assets')
            login = client.post('/api/v1/auth/login', json={'email': 'http@example.test', 'password': password}, headers={'Origin': base_url})
            assert login.status_code == 200
            assert any('HttpOnly' in value for value in login.headers.get_list('set-cookie'))
            client.headers.update({'X-Workspace-ID': identity['org_id'], 'X-CSRF-Token': client.cookies['fp_csrf'], 'Origin': base_url})
            checks.append('Real HTTP login establishes cookie authentication')
            blocked = client.post('/api/v1/projects', json={'name': 'Blocked'}, headers={'Origin': 'https://another.example'})
            assert blocked.status_code == 403
            checks.append('Cross-origin mutation is rejected')
            definition = {'nodes': [{'id': 'map', 'type': 'set', 'values': {'result': {'$ref': 'input.value'}}}, {'id': 'review', 'type': 'approval', 'depends_on': ['map'], 'message': 'Approve the local test.'}]}
            created = client.post('/api/v1/workflows', json={'name': 'HTTP smoke workflow', 'project_id': identity['project_id'], 'definition': definition})
            assert created.status_code == 201, created.text
            workflow_id = created.json()['id']
            assert client.post(f'/api/v1/workflows/{workflow_id}/publish', json={'expected_revision': 1}).status_code == 201
            checks.append('Create and publish through the deployed HTTP process')
            path = f'/api/v1/workflows/{workflow_id}/runs'
            run = client.post(path, json={'input': {'value': 42}}, headers={'Idempotency-Key': 'http-smoke'})
            assert run.status_code == 202, run.text
            run_id = run.json()['id']
            duplicate = client.post(path, json={'input': {'value': 42}}, headers={'Idempotency-Key': 'http-smoke'})
            assert duplicate.status_code == 200
            assert duplicate.json()['id'] == run_id
            checks.append('Duplicate HTTP submission returns the existing execution')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                detail = client.get(f'/api/v1/runs/{run_id}').json()
                if detail['status'] == 'waiting':
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Separate worker did not reach approval')
            assert detail['steps'][0]['output'] == {'result': 42}
            checks.append('Separate worker persists output and a durable approval wait')
            result = client.post(f'/api/v1/runs/{run_id}/steps/review/approval', json={'approved': True, 'note': 'HTTP smoke check'})
            assert result.status_code == 200
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if client.get(f'/api/v1/runs/{run_id}').json()['status'] == 'succeeded':
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Worker did not complete approved execution')
            checks.append('Worker resumes after HTTP approval and completes the run')
            assert client.post('/api/v1/auth/logout').status_code == 204
            assert client.get('/api/v1/auth/me').status_code == 401
            checks.append('Logout revokes the session over HTTP')
        db.engine.dispose()
    report = {'status': 'passed', 'transport': 'real loopback HTTP with separate API and worker processes', 'checks': checks, 'count': len(checks)}
    (ROOT / 'verification/http-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
