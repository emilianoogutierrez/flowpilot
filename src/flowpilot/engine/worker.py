import hashlib
import json
import os
import signal
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import and_, func, or_, select, update

from flowpilot.config import Settings, get_settings
from flowpilot.crypto import Vault
from flowpilot.db import Database
from flowpilot.engine.definition import (
    AiNode,
    ApprovalNode,
    ConditionNode,
    Definition,
    DelayNode,
    HttpNode,
    SetNode,
    evaluate,
    resolve,
    topological_order,
)
from flowpilot.errors import DomainError, ExecutionError
from flowpilot.integrations.ai import AiRuntime, NodeResult
from flowpilot.integrations.http import HttpTransport, SafeHttpTransport, require_success
from flowpilot.models import (
    Attempt,
    Run,
    StepRun,
    WorkerHeartbeat,
    Workflow,
    WorkflowVersion,
    new_id,
)
from flowpilot.services import get_credential
from flowpilot.telemetry import build_tracer, log_event

DONE_STEPS = {"succeeded", "skipped"}


@dataclass(frozen=True)
class Claim:
    run_id: str
    token: str


@dataclass(frozen=True)
class WorkItem:
    claim: Claim
    node: Any
    context: dict
    key: str | None
    credential_host: str | None
    attempt_id: str
    dry_run: bool


def retry_delay(run_id: str, node_id: str, attempt: int, initial: float, maximum: float) -> float:
    fraction = int(hashlib.sha256(f"{run_id}:{node_id}:{attempt}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return min(maximum, initial * 2 ** (attempt - 1)) * (0.75 + fraction * 0.25)


class Worker:
    def __init__(self, db: Database, settings: Settings, transport: HttpTransport | None = None, worker_id: str | None = None):
        self.db = db
        self.settings = settings
        self.vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{new_id()[:8]}"
        self.transport = transport or SafeHttpTransport(settings.egress_hosts, settings.max_response_bytes)
        self.ai = AiRuntime(self.transport)
        self.tracer_provider, self.tracer = build_tracer(settings.otlp_endpoint)
        self.stopping = threading.Event()

    def claim(self, now: float | None = None) -> Claim | None:
        now = time.time() if now is None else now
        with self.db.transaction() as session:
            heartbeat = session.get(WorkerHeartbeat, self.id)
            if heartbeat:
                heartbeat.seen_at = now
            else:
                session.add(WorkerHeartbeat(id=self.id, seen_at=now))
            eligible = or_(and_(Run.status.in_(["queued", "waiting", "retry_wait"]), Run.available_at <= now), and_(Run.status == "running", Run.lease_until < now))
            candidates = session.scalars(select(Run).where(eligible).order_by(Run.available_at, Run.created_at).limit(20).with_for_update(skip_locked=True)).all()
            for run in candidates:
                workflow = session.scalar(select(Workflow).where(Workflow.id == run.workflow_id).with_for_update(skip_locked=True))
                if not workflow:
                    continue
                active = session.scalar(select(func.count()).select_from(Run).where(Run.workflow_id == workflow.id, Run.status == "running", Run.lease_until >= now, Run.id != run.id)) or 0
                if active >= workflow.max_concurrency:
                    continue
                if run.status == "running":
                    active_steps = session.scalars(select(StepRun).where(StepRun.run_id == run.id, StepRun.status == "running")).all()
                    version = session.get(WorkflowVersion, run.version_id)
                    nodes = {node.id: node for node in Definition.model_validate(version.definition).nodes}
                    uncertain = False
                    for step in active_steps:
                        node = nodes[step.node_id]
                        unsafe_http = isinstance(node, HttpNode) and node.method != "GET" and not node.receiver_supports_idempotency
                        if unsafe_http and not run.dry_run:
                            self._fail(run, step, "outcome_unknown", now)
                            uncertain = True
                        else:
                            step.status = "pending"
                            step.error_code = "worker_lease_expired"
                    session.execute(update(Attempt).where(Attempt.run_id == run.id, Attempt.status == "running").values(status="abandoned", finished_at=now, error_code="worker_lease_expired"))
                    if uncertain:
                        continue
                token = new_id()
                run.status = "running"
                run.lease_token = token
                run.lease_until = now + self.settings.lease_seconds
                run.worker_id = self.id
                if run.started_at is None:
                    run.started_at = now
                return Claim(run.id, token)
        return None

    def prepare(self, claim: Claim, now: float | None = None) -> WorkItem | None:
        now = time.time() if now is None else now
        with self.db.transaction() as session:
            run = session.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
            if not self._owns(run, claim, now):
                return None
            version = session.get(WorkflowVersion, run.version_id)
            definition = Definition.model_validate(version.definition)
            steps = {step.node_id: step for step in session.scalars(select(StepRun).where(StepRun.run_id == run.id))}
            context = {"input": self.vault.open(run.input_cipher, f"input:{run.org_id}:{run.id}"), "steps": {}}
            for step in steps.values():
                if step.output_cipher:
                    context["steps"][step.node_id] = self.vault.open(step.output_cipher, f"output:{run.org_id}:{run.id}:{step.node_id}")
            for node in topological_order(definition.nodes):
                step = steps[node.id]
                if step.status in DONE_STEPS:
                    continue
                parents = [steps[parent] for parent in node.depends_on]
                if any(parent.status not in DONE_STEPS for parent in parents):
                    continue
                should_skip = bool(parents) and (any(parent.status == "skipped" for parent in parents) if node.join == "all" else all(parent.status == "skipped" for parent in parents))
                try:
                    should_skip = should_skip or bool(node.when and not evaluate(node.when, context))
                except (ValueError, TypeError):
                    self._fail(run, step, "predicate_invalid", now)
                    return None
                if should_skip:
                    step.status = "skipped"
                    continue
                if isinstance(node, DelayNode):
                    if step.ready_at is None:
                        step.ready_at = now + node.seconds
                    if step.ready_at > now:
                        step.status = "waiting"
                        self._release(run, "waiting", step.ready_at)
                        return None
                    self._complete_step(run, step, {"waited_seconds": node.seconds}, now)
                    context["steps"][node.id] = {"waited_seconds": node.seconds}
                    continue
                if isinstance(node, ApprovalNode):
                    if step.ready_at is not None and step.ready_at <= now:
                        self._fail(run, step, "approval_expired", now)
                    else:
                        step.status = "awaiting_approval"
                        step.ready_at = step.ready_at or now + node.expires_after
                        self._release(run, "waiting", step.ready_at)
                    return None
                if step.attempts >= node.retry.max_attempts:
                    self._fail(run, step, "attempts_exhausted", now)
                    return None
                key, host = None, None
                credential_id = getattr(node, "credential_id", None)
                if credential_id and not run.dry_run:
                    try:
                        credential, key = get_credential(session, self.vault, run, credential_id)
                        host = credential.allowed_host
                    except DomainError:
                        self._fail(run, step, "credential_unavailable", now)
                        return None
                step.attempts += 1
                step.status = "running"
                step.error_code = None
                attempt = Attempt(run_id=run.id, node_id=node.id, number=step.attempts, lease_token=claim.token, started_at=now)
                session.add(attempt)
                session.flush()
                return WorkItem(claim, node, context, key, host, attempt.id, run.dry_run)
            if all(step.status in DONE_STEPS for step in steps.values()):
                run.status = "succeeded"
                run.finished_at = now
                run.lease_token = None
                run.lease_until = None
            else:
                self._release(run, "queued", now)
        return None

    def execute(self, item: WorkItem) -> NodeResult:
        node, context = item.node, item.context
        if isinstance(node, SetNode):
            return NodeResult(resolve(node.values, context))
        if isinstance(node, ConditionNode):
            return NodeResult({"match": evaluate(node.predicate, context)})
        if isinstance(node, AiNode):
            return self.ai.execute(node, resolve(node.prompt, context), item.key, item.dry_run)
        if isinstance(node, HttpNode):
            if item.dry_run:
                return NodeResult({"simulated": True, "status": 200, "body": None})
            host = urlsplit(node.url).hostname
            if item.key and host != item.credential_host:
                raise ExecutionError("credential_host_mismatch")
            effect_key = hashlib.sha256(f"{item.claim.run_id}:{node.id}".encode()).hexdigest()
            headers = {**node.headers, "Idempotency-Key": effect_key}
            if item.key:
                headers["Authorization"] = f"Bearer {item.key}"
            retry_safe = node.method == "GET" or node.receiver_supports_idempotency
            try:
                result = self.transport.request(node.method, node.url, headers, resolve(node.body, context), node.timeout_seconds)
            except ExecutionError as error:
                if not retry_safe:
                    error.retryable = False
                raise
            require_success(result, allow_retry=retry_safe)
            return NodeResult({"status": result.status, "body": result.body})
        raise ExecutionError("node_not_supported")

    def finish(self, item: WorkItem, result: NodeResult | None, error: ExecutionError | None, duration_ms: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.db.transaction() as session:
            run = session.scalar(select(Run).where(Run.id == item.claim.run_id).with_for_update())
            if not self._owns(run, item.claim, now):
                return False
            step = session.get(StepRun, (run.id, item.node.id))
            attempt = session.get(Attempt, item.attempt_id)
            attempt.finished_at = now
            attempt.duration_ms = duration_ms
            step.duration_ms += duration_ms
            if result and len(json.dumps(result.data).encode()) > self.settings.max_response_bytes:
                error = ExecutionError("node_output_too_large")
            if error:
                attempt.status = "failed"
                attempt.error_code = error.code
                step.error_code = error.code
                if error.retryable and step.attempts < item.node.retry.max_attempts:
                    delay = retry_delay(run.id, step.node_id, step.attempts, item.node.retry.initial_seconds, item.node.retry.max_seconds)
                    if error.retry_after:
                        delay = max(delay, error.retry_after)
                    step.status = "retry_wait"
                    step.ready_at = now + delay
                    self._release(run, "retry_wait", step.ready_at)
                else:
                    self._fail(run, step, error.code, now)
            else:
                attempt.status = "succeeded"
                self._complete_step(run, step, result.data, now)
                step.usage = result.usage
                self._release(run, "queued", now)
            return True

    def tick(self) -> bool:
        claim = self.claim()
        if not claim:
            return False
        item = self.prepare(claim)
        if item is None:
            return True
        started = time.monotonic()
        result, error = None, None
        with self.tracer.start_as_current_span("workflow.step", attributes={"workflow.run_id": claim.run_id, "workflow.node_id": item.node.id, "workflow.node_type": item.node.type}):
            try:
                result = self.execute(item)
            except ExecutionError as failure:
                error = failure
            except (ValueError, TypeError, KeyError):
                error = ExecutionError("node_input_invalid")
            except Exception as failure:
                log_event("worker.unhandled_error", run_id=claim.run_id, error_type=type(failure).__name__)
                error = ExecutionError("internal_execution_error")
        accepted = self.finish(item, result, error, (time.monotonic() - started) * 1000)
        log_event("step.finished", run_id=claim.run_id, node_id=item.node.id, error=error.code if error else None, accepted=accepted)
        return True

    def run_forever(self):
        while not self.stopping.is_set():
            try:
                if not self.tick():
                    self.stopping.wait(self.settings.poll_seconds)
            except Exception as error:
                log_event("worker.loop_error", error_type=type(error).__name__)
                self.stopping.wait(2)
        self.tracer_provider.shutdown()

    @staticmethod
    def _owns(run: Run | None, claim: Claim, now: float) -> bool:
        return bool(run and run.status == "running" and run.lease_token == claim.token and run.lease_until and run.lease_until >= now)

    @staticmethod
    def _release(run: Run, status: str, available_at: float):
        run.status = status
        run.available_at = available_at
        run.lease_until = None
        run.lease_token = None

    def _complete_step(self, run: Run, step: StepRun, output: Any, _now: float):
        step.output_cipher = self.vault.seal(output, f"output:{run.org_id}:{run.id}:{step.node_id}")
        step.status = "succeeded"
        step.error_code = None

    @staticmethod
    def _fail(run: Run, step: StepRun, error_code: str, now: float):
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = now
        run.lease_token = None
        run.lease_until = None
        step.status = "failed"
        step.error_code = error_code


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    db = Database(settings.database_url)
    worker = Worker(db, settings)
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    try:
        worker.run_forever()
    finally:
        db.close()


if __name__ == "__main__":
    main()
