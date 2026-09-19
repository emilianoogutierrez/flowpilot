import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from flowpilot.engine.worker import Worker
from flowpilot.integrations.ai import NodeResult
from flowpilot.integrations.http import HttpResult
from flowpilot.models import Attempt, Run, StepRun, Workflow


def drain(worker, limit=30):
    for _ in range(limit):
        if not worker.tick():
            return
    raise AssertionError('Worker did not settle within the expected number of steps')


class RecordingTransport:
    def __init__(self, statuses=None):
        self.calls = []
        self.statuses = list(statuses or [200])

    def request(self, method, url, headers, body, timeout):
        self.calls.append({'method': method, 'url': url, 'headers': headers, 'body': body})
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return HttpResult(status, {'accepted': True}, {})


def test_workflow_completes_and_preserves_outputs(worker, make_workflow, make_run, db, vault):
    workflow = make_workflow(nodes=[
        {'id': 'first', 'type': 'set', 'values': {'value': {'$ref': 'input.value'}}},
        {'id': 'second', 'type': 'set', 'depends_on': ['first'], 'values': {'copied': {'$ref': 'steps.first.value'}}},
    ])
    run_id = make_run(workflow['workflow_id'], {'value': 12})
    drain(worker)
    with db.sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == 'succeeded'
        step = session.get(StepRun, (run_id, 'second'))
        assert vault.open(step.output_cipher, f'output:{run.org_id}:{run.id}:second') == {'copied': 12}
        assert step.attempts == 1


def test_condition_skips_branch_and_all_join(worker, make_workflow, make_run, db):
    workflow = make_workflow(nodes=[
        {'id': 'condition', 'type': 'condition', 'predicate': {'left': False, 'right': True}},
        {'id': 'branch', 'type': 'set', 'depends_on': ['condition'], 'when': {'left': {'$ref': 'steps.condition.match'}, 'right': True}, 'values': {}},
        {'id': 'after', 'type': 'set', 'depends_on': ['branch'], 'values': {}},
    ])
    run_id = make_run(workflow['workflow_id'])
    drain(worker)
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'succeeded'
        assert session.get(StepRun, (run_id, 'branch')).status == 'skipped'
        assert session.get(StepRun, (run_id, 'after')).status == 'skipped'


def test_any_join_proceeds_after_one_branch(worker, make_workflow, make_run, db):
    workflow = make_workflow(nodes=[
        {'id': 'a', 'type': 'set', 'values': {}, 'when': {'left': False, 'right': True}},
        {'id': 'b', 'type': 'set', 'values': {}},
        {'id': 'join', 'type': 'set', 'depends_on': ['a', 'b'], 'join': 'any', 'values': {'ok': True}},
    ])
    run_id = make_run(workflow['workflow_id'])
    drain(worker)
    with db.sessions() as session:
        assert session.get(StepRun, (run_id, 'join')).status == 'succeeded'


def test_delay_survives_new_worker_without_sleep(worker, make_workflow, make_run, db, settings):
    workflow = make_workflow(nodes=[{'id': 'wait', 'type': 'delay', 'seconds': 100}, {'id': 'after', 'type': 'set', 'depends_on': ['wait'], 'values': {}}])
    run_id = make_run(workflow['workflow_id'])
    assert worker.tick()
    with db.sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == 'waiting'
        wake = run.available_at
        assert run.lease_token is None
    other = Worker(db, settings, worker_id='new-process')
    assert other.claim(now=wake - 1) is None
    claim = other.claim(now=wake + 1)
    item = other.prepare(claim, now=wake + 1)
    assert item.node.id == 'after'
    assert other.finish(item, other.execute(item), None, 1, now=wake + 2)
    claim = other.claim(now=wake + 3)
    other.prepare(claim, now=wake + 3)
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'succeeded'


def test_crashed_worker_recovers_with_fencing(worker, make_workflow, make_run, db, settings):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    first = worker.claim()
    item = worker.prepare(first)
    future = time.time() + settings.lease_seconds + 1
    replacement = Worker(db, settings, worker_id='replacement')
    second = replacement.claim(now=future)
    assert second.run_id == first.run_id
    assert second.token != first.token
    assert not worker.finish(item, NodeResult({'wrong': True}), None, 1, now=future)
    recovered = replacement.prepare(second, now=future)
    assert replacement.finish(recovered, replacement.execute(recovered), None, 1, now=future + 1)
    with db.sessions() as session:
        attempts = session.scalars(select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.number)).all()
        assert [attempt.status for attempt in attempts] == ['abandoned', 'succeeded']
        assert len(attempts) == 2


def test_cancellation_fences_late_worker_results(worker, client, make_workflow, make_run, db):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    claim = worker.claim()
    item = worker.prepare(claim)
    assert client.post(f'/api/v1/runs/{run_id}/cancel').status_code == 200
    assert not worker.finish(item, NodeResult({'value': 'late'}), None, 1)
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'cancelled'
        assert session.get(StepRun, (run_id, 'first')).output_cipher is None


def test_expired_unsafe_side_effect_requires_review(worker, make_workflow, make_run, db, settings):
    workflow = make_workflow(nodes=[{'id': 'send', 'type': 'http', 'method': 'POST', 'url': 'https://api.example.com/send'}])
    run_id = make_run(workflow['workflow_id'])
    claim = worker.claim()
    worker.prepare(claim)
    assert worker.claim(now=time.time() + settings.lease_seconds + 1) is None
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'failed'
        assert session.get(Run, run_id).error_code == 'outcome_unknown'


def test_retry_wait_is_durable_and_effect_key_is_stable(make_workflow, make_run, db, settings):
    workflow = make_workflow(nodes=[{'id': 'send', 'type': 'http', 'method': 'POST', 'receiver_supports_idempotency': True, 'url': 'https://api.example.com/send'}])
    run_id = make_run(workflow['workflow_id'])
    transport = RecordingTransport([503, 200])
    instance = Worker(db, settings, transport=transport)
    assert instance.tick()
    with db.transaction() as session:
        run = session.get(Run, run_id)
        assert run.status == 'retry_wait'
        assert run.available_at > time.time()
        run.available_at = time.time() - 1
    drain(instance)
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'succeeded'
        assert session.get(StepRun, (run_id, 'send')).attempts == 2
    assert transport.calls[0]['headers']['Idempotency-Key'] == transport.calls[1]['headers']['Idempotency-Key']


def test_unsafe_http_is_not_automatically_retried(make_workflow, make_run, db, settings):
    workflow = make_workflow(nodes=[{'id': 'send', 'type': 'http', 'method': 'POST', 'url': 'https://api.example.com/send'}])
    run_id = make_run(workflow['workflow_id'])
    transport = RecordingTransport([503])
    drain(Worker(db, settings, transport=transport))
    assert len(transport.calls) == 1
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'failed'


def test_dry_run_never_sends_http(make_workflow, make_run, db, settings):
    workflow = make_workflow(nodes=[{'id': 'send', 'type': 'http', 'method': 'POST', 'url': 'https://api.example.com/send'}])
    run_id = make_run(workflow['workflow_id'], dry_run=True)
    transport = RecordingTransport()
    drain(Worker(db, settings, transport=transport))
    assert transport.calls == []
    with db.sessions() as session:
        assert session.get(Run, run_id).status == 'succeeded'


def test_approval_release_and_rejection(worker, client, make_workflow, make_run, db):
    workflow = make_workflow(nodes=[{'id': 'review', 'type': 'approval', 'message': 'Review'}, {'id': 'after', 'type': 'set', 'depends_on': ['review'], 'values': {'done': True}}])
    run_id = make_run(workflow['workflow_id'])
    drain(worker)
    assert client.get(f'/api/v1/runs/{run_id}').json()['steps'][0]['status'] == 'awaiting_approval'
    assert client.post(f'/api/v1/runs/{run_id}/steps/review/approval', json={'approved': True}).status_code == 200
    drain(worker)
    assert client.get(f'/api/v1/runs/{run_id}').json()['status'] == 'succeeded'
    assert client.post(f'/api/v1/runs/{run_id}/steps/review/approval', json={'approved': True}).status_code == 409
    rejected = make_run(workflow['workflow_id'], key='reject')
    drain(worker)
    assert client.post(f'/api/v1/runs/{rejected}/steps/review/approval', json={'approved': False}).status_code == 200
    assert client.get(f'/api/v1/runs/{rejected}').json()['error_code'] == 'approval_rejected'


def test_approval_expiration(worker, make_workflow, make_run, db):
    workflow = make_workflow(nodes=[{'id': 'review', 'type': 'approval', 'message': 'Review', 'expires_after': 60}])
    run_id = make_run(workflow['workflow_id'])
    worker.tick()
    future = time.time() + 65
    claim = worker.claim(now=future)
    assert worker.prepare(claim, now=future) is None
    with db.sessions() as session:
        assert session.get(Run, run_id).error_code == 'approval_expired'


def test_concurrent_claims_are_unique_and_limited(make_workflow, make_run, db, settings):
    workflow = make_workflow()
    for index in range(8):
        make_run(workflow['workflow_id'], key=f'event-{index}')

    def claim(index):
        return Worker(db, settings, worker_id=f'worker-{index}').claim()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = [item for item in pool.map(claim, range(8)) if item]
    assert len(claims) == 2
    assert len({item.run_id for item in claims}) == 2


def test_saturated_workflow_does_not_starve_other_workflows(
    worker, make_workflow, make_run, db, settings
):
    saturated = make_workflow()
    available = make_workflow()

    with db.transaction() as session:
        session.get(Workflow, saturated['workflow_id']).max_concurrency = 1
        session.get(Workflow, available['workflow_id']).max_concurrency = 1

    active_run_id = make_run(saturated['workflow_id'], key='active-run')
    active_claim = worker.claim()
    assert active_claim is not None
    assert active_claim.run_id == active_run_id

    for index in range(20):
        make_run(saturated['workflow_id'], key=f'saturated-{index}')

    available_run_id = make_run(available['workflow_id'], key='available-run')
    other = Worker(db, settings, worker_id='fair-worker')
    claim = other.claim()

    assert claim is not None
    assert claim.run_id == available_run_id


def test_worker_lease_uses_database_clock(worker, make_workflow, make_run, db, settings, monkeypatch):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    database_now = 1_000_000.25

    with db.transaction() as session:
        session.get(Run, run_id).available_at = database_now - 1

    monkeypatch.setattr(db, 'current_time', lambda _session: database_now)
    claim = worker.claim()

    assert claim is not None
    with db.sessions() as session:
        run = session.get(Run, run_id)
        assert run.started_at == pytest.approx(database_now)
        assert run.lease_until == pytest.approx(database_now + settings.lease_seconds)


def test_lease_configuration_keeps_margin_over_external_timeout(settings):
    with pytest.raises(ValueError):
        settings.__class__(master_keys=settings.master_keys, lease_seconds=59)


def test_missing_runtime_reference_is_node_input_invalid(worker, make_workflow, make_run, db):
    workflow = make_workflow(nodes=[
        {'id': 'first', 'type': 'set', 'values': {'value': 1}},
        {
            'id': 'second',
            'type': 'set',
            'depends_on': ['first'],
            'values': {'copied': {'$ref': 'steps.first.missing'}},
        },
    ])
    run_id = make_run(workflow['workflow_id'])

    drain(worker)

    with db.sessions() as session:
        assert session.get(Run, run_id).error_code == 'node_input_invalid'


def test_internal_key_error_is_not_misclassified(
    worker, make_workflow, make_run, db, monkeypatch
):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])

    def raise_internal_error(_item):
        raise KeyError('implementation bug')

    monkeypatch.setattr(worker, 'execute', raise_internal_error)
    assert worker.tick()

    with db.sessions() as session:
        assert session.get(Run, run_id).error_code == 'internal_execution_error'


def test_running_execution_keeps_original_definition(worker, client, make_workflow, make_run, db):
    workflow = make_workflow()
    run_id = make_run(workflow['workflow_id'])
    changed = {'nodes': [{'id': 'changed', 'type': 'set', 'values': {'answer': 999}}]}
    assert client.patch(f"/api/v1/workflows/{workflow['workflow_id']}", json={'definition': changed, 'expected_revision': 1}).status_code == 200
    assert client.post(f"/api/v1/workflows/{workflow['workflow_id']}/publish", json={'expected_revision': 2}).status_code == 201
    drain(worker)
    detail = client.get(f'/api/v1/runs/{run_id}').json()
    assert detail['version'] == 1
    assert detail['steps'][0]['id'] == 'first'
    assert detail['steps'][0]['output']['answer'] == 42


def test_credential_version_is_pinned_at_enqueue(client, identity, make_workflow, make_run, db, settings):
    created = client.post('/api/v1/credentials', json={'name': 'HTTP', 'kind': 'http', 'project_id': identity['project_id'], 'allowed_host': 'api.example.com', 'value': 'first-long-api-token'}).json()
    workflow = make_workflow(nodes=[{'id': 'http', 'type': 'http', 'url': 'https://api.example.com/data', 'credential_id': created['id']}])
    make_run(workflow['workflow_id'])
    assert client.post(f"/api/v1/credentials/{created['id']}/rotate", json={'value': 'second-long-api-token'}).status_code == 200
    transport = RecordingTransport()
    drain(Worker(db, settings, transport=transport))
    assert transport.calls[0]['headers']['Authorization'] == 'Bearer first-long-api-token'


def test_revocation_blocks_pinned_credential(client, identity, make_workflow, make_run, db, settings):
    created = client.post('/api/v1/credentials', json={'name': 'HTTP', 'kind': 'http', 'project_id': identity['project_id'], 'allowed_host': 'api.example.com', 'value': 'first-long-api-token'}).json()
    workflow = make_workflow(nodes=[{'id': 'http', 'type': 'http', 'url': 'https://api.example.com/data', 'credential_id': created['id']}])
    run_id = make_run(workflow['workflow_id'])
    client.post(f"/api/v1/credentials/{created['id']}/revoke")
    transport = RecordingTransport()
    drain(Worker(db, settings, transport=transport))
    assert not transport.calls
    with db.sessions() as session:
        assert session.get(Run, run_id).error_code == 'credential_unavailable'


def test_credential_is_never_sent_to_other_host(client, identity, make_workflow, make_run, db, settings):
    created = client.post('/api/v1/credentials', json={'name': 'HTTP', 'kind': 'http', 'project_id': identity['project_id'], 'allowed_host': 'api.example.com', 'value': 'first-long-api-token'}).json()
    workflow = make_workflow(nodes=[{'id': 'http', 'type': 'http', 'url': 'https://different.example.com/data', 'credential_id': created['id']}])
    run_id = make_run(workflow['workflow_id'])
    transport = RecordingTransport()
    drain(Worker(db, settings, transport=transport))
    assert not transport.calls
    with db.sessions() as session:
        assert session.get(Run, run_id).error_code == 'credential_host_mismatch'
