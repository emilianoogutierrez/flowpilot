import base64
import json
import os
import sys
import time

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from flowpilot import cli
from flowpilot.api.auth import verify_password
from flowpilot.crypto import Vault
from flowpilot.models import AuditEvent, CredentialVersion, Run, StepRun, User, Workflow


def test_create_user_rejects_short_password_and_duplicate(db, identity):
    with pytest.raises(ValueError, match='12 characters'):
        cli.create_user(db, 'short@example.test', 'Short', 'short')
    with pytest.raises(ValueError, match='already exists'):
        cli.create_user(db, 'owner@example.test', 'Owner', 'long-enough-password')


def test_reset_password_revokes_existing_sessions(monkeypatch, client, db, settings):
    monkeypatch.setattr(sys, 'argv', ['flowpilot', 'reset-password', 'owner@example.test'])
    monkeypatch.setattr(cli, 'get_settings', lambda: settings)
    monkeypatch.setattr(cli.getpass, 'getpass', lambda prompt: 'new-password-long-enough')
    cli.main()
    with db.sessions() as session:
        user = session.scalar(select(User).where(User.email == 'owner@example.test'))
        assert verify_password('new-password-long-enough', user.password_hash)
    assert client.get('/api/v1/auth/me').status_code == 401


def test_purge_removes_closed_run_but_preserves_audit(monkeypatch, db, settings, make_workflow, make_run, worker):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    for _ in range(3):
        worker.tick()
    with db.transaction() as session:
        session.get(Run, run_id).finished_at = time.time() - 60 * 86400
    monkeypatch.setattr(sys, 'argv', ['flowpilot', 'purge'])
    monkeypatch.setattr(cli, 'get_settings', lambda: settings)
    cli.main()
    with db.sessions() as session:
        assert session.get(Run, run_id) is None
        assert session.scalars(select(StepRun)).all() == []
        assert session.scalars(select(AuditEvent)).all()


def test_master_rotation_preserves_inputs_outputs_and_credentials(monkeypatch, client, db, settings, identity, make_workflow, make_run, worker):
    created = client.post('/api/v1/credentials', json={'name': 'Rotation check', 'kind': 'anthropic', 'project_id': identity['project_id'], 'value': 'test-rotation-value'}).json()
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'], {'value': 42})
    for _ in range(3):
        worker.tick()
    keys = json.loads(settings.master_keys.get_secret_value())
    keys['v2'] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    rotated = settings.model_copy(update={'master_keys': SecretStr(json.dumps(keys)), 'active_key_id': 'v2'})
    monkeypatch.setattr(sys, 'argv', ['flowpilot', 'rotate-master-key'])
    monkeypatch.setattr(cli, 'get_settings', lambda: rotated)
    cli.main()
    vault = Vault(json.dumps({'v2': keys['v2']}), 'v2')
    with db.sessions() as session:
        run = session.get(Run, run_id)
        assert vault.open(run.input_cipher, f'input:{identity["org_id"]}:{run_id}') == {'value': 42}
        step = session.get(StepRun, (run_id, 'first'))
        assert vault.open(step.output_cipher, f'output:{identity["org_id"]}:{run_id}:first') == {'answer': 42}
        row = session.get(CredentialVersion, (created['id'], 1))
        assert vault.open(row.ciphertext, f'credential:{identity["org_id"]}:{created["id"]}:1') == 'test-rotation-value'
        stored = session.get(Workflow, workflow['workflow_id'])
        assert vault.open(stored.webhook_cipher, f'webhook:{identity["org_id"]}:{stored.id}') == workflow['secret']


def test_cli_validation_does_not_need_runtime_credentials(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'workflow.json'
    path.write_text(json.dumps({'nodes': [{'id': 'one', 'type': 'set', 'values': {}}]}))
    monkeypatch.setattr(sys, 'argv', ['flowpilot', 'validate', str(path)])
    cli.main()
    assert '1 nodes' in capsys.readouterr().out


def test_cli_schema_export_is_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['flowpilot', 'export-schema'])
    cli.main()
    assert json.loads(capsys.readouterr().out)['title'] == 'Definition'


def test_demo_is_never_created_in_production(db, settings):
    with pytest.raises(ValueError, match='disabled in production'):
        cli.seed_demo(db, settings.model_copy(update={'environment': 'production'}))
