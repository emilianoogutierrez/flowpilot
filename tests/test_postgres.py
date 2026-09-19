import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from flowpilot.cli import create_user, migrate
from flowpilot.crypto import Vault
from flowpilot.db import Database
from flowpilot.engine.definition import Definition
from flowpilot.engine.worker import Worker
from flowpilot.services import create_workflow, enqueue, publish

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres(settings):
    target = os.getenv('TEST_DATABASE_URL')
    if not target:
        pytest.skip('TEST_DATABASE_URL is not configured; PostgreSQL was not exercised')
    url = make_url(target)
    if url.get_backend_name() != 'postgresql':
        pytest.fail('TEST_DATABASE_URL must be PostgreSQL')
    schema = 'test_' + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = url.update_query_dict({'options': f'-csearch_path={schema}'})
    configured = settings.model_copy(update={'database_url': scoped.render_as_string(hide_password=False)})
    migrate(configured.database_url)
    db = Database(configured.database_url)
    try:
        yield db, configured
    finally:
        db.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def published_job(db, settings):
    identity = create_user(db, 'postgres@example.test', 'Postgres test', 'test-password-long-enough', 'Postgres test')
    vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
    with db.transaction() as session:
        workflow, _ = create_workflow(session, vault, identity['org_id'], identity['user_id'], identity['project_id'], 'Concurrency', '', Definition(nodes=[{'id': 'map', 'type': 'set', 'values': {'result': True}}]))
        workflow.max_concurrency = 16
        publish(session, identity['org_id'], identity['user_id'], workflow.id, 1)
        return identity, vault, workflow.id


def test_postgres_skip_locked_claims_are_unique(postgres):
    db, settings = postgres
    identity, vault, workflow_id = published_job(db, settings)
    with db.transaction() as session:
        for index in range(20):
            enqueue(session, vault, identity['org_id'], identity['user_id'], workflow_id, {}, f'job-{index}', 100)
    workers = [Worker(db, settings, worker_id=f'postgres-worker-{index}') for index in range(8)]
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda worker: worker.claim(), workers))
        ids = [claim.run_id for claim in claims if claim]
        assert ids
        assert len(ids) == len(set(ids))
    finally:
        for worker in workers:
            worker.tracer_provider.shutdown()


def test_postgres_concurrent_duplicate_submission_creates_one_run(postgres):
    db, settings = postgres
    identity, vault, workflow_id = published_job(db, settings)
    def submit(_):
        with db.transaction() as session:
            run, created = enqueue(session, vault, identity['org_id'], identity['user_id'], workflow_id, {}, 'same-event', 100)
            return run.id, created
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    assert len({run_id for run_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
