import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpilot.api.app import create_app
from flowpilot.cli import create_user, migrate
from flowpilot.config import Settings
from flowpilot.crypto import Vault
from flowpilot.db import Database
from flowpilot.engine.definition import Definition
from flowpilot.engine.worker import Worker

from flowpilot.services import create_workflow, enqueue, publish


@pytest.fixture
def settings(tmp_path):
    return Settings(environment="test", database_url=f"sqlite:///{tmp_path / 'test.db'}", master_keys=json.dumps({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()}), allowed_hosts=["testserver", "localhost", "127.0.0.1"], public_origin="http://testserver", egress_hosts=["api.example.com", "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com"], metrics_token="test-metrics-token-that-is-long-enough", static_dir=Path(__file__).resolve().parents[1] / "web/dist")


@pytest.fixture
def db(settings):
    migrate(settings.database_url)
    database = Database(settings.database_url)
    yield database
    database.engine.dispose()


@pytest.fixture
def vault(settings):
    return Vault(settings.master_keys.get_secret_value(), settings.active_key_id)


@pytest.fixture
def identity(db):
    return create_user(db, "owner@example.test", "Owner", "correct horse battery staple", "Test workspace")


@pytest.fixture
def client(settings, db, identity):
    with TestClient(create_app(settings, db)) as client:
        result = client.post('/api/v1/auth/login', json={"email": "owner@example.test", "password": "correct horse battery staple"})
        assert result.status_code == 200
        client.headers.update({"x-csrf-token": client.cookies['fp_csrf'], "x-workspace-id": identity['org_id']})
        yield client


@pytest.fixture
def make_workflow(db, vault, identity):
    def make(nodes=None, input_schema=None):
        definition = Definition.model_validate({"nodes": nodes or [{"id": "first", "type": "set", "values": {"answer": 42}}], "input_schema": input_schema or {"type": "object"}})
        with db.transaction() as session:
            workflow, secret = create_workflow(session, vault, identity['org_id'], identity['user_id'], identity['project_id'], 'Test workflow', 'A test', definition)
            version = publish(session, identity['org_id'], identity['user_id'], workflow.id, 1)
            return {"workflow_id": workflow.id, "version_id": version.id, "secret": secret, "definition": definition}
    return make


@pytest.fixture
def make_run(db, vault, settings, identity):
    def make(workflow_id, payload=None, key="test-event", dry_run=False):
        with db.transaction() as session:
            run, _ = enqueue(session, vault, identity['org_id'], identity['user_id'], workflow_id, payload or {}, key, settings.max_queued_runs, dry_run=dry_run)
            return run.id
    return make


@pytest.fixture
def worker(db, settings):
    instance = Worker(db, settings, worker_id='worker-test')
    yield instance
    instance.tracer_provider.shutdown()
