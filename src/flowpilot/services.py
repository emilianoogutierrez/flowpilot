import json
import secrets
import time


from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flowpilot.crypto import Vault, json_digest
from flowpilot.db import current_time
from flowpilot.engine.definition import Definition
from flowpilot.errors import DomainError
from flowpilot.models import (
    AuditEvent,
    Credential,
    CredentialVersion,
    Project,
    Run,
    StepRun,
    Workflow,
    WorkflowVersion,
    new_id,
)

TERMINAL_RUNS = {"succeeded", "failed", "cancelled"}
WRITE_ROLES = {"owner", "admin", "developer"}


def audit(session: Session, org_id: str, actor_id: str | None, action: str, resource_id: str, **detail):
    session.add(AuditEvent(org_id=org_id, actor_id=actor_id, action=action, resource_id=resource_id, detail=detail))


def workflow_for(session: Session, org_id: str, workflow_id: str, lock: bool = False) -> Workflow:
    query = select(Workflow).where(Workflow.org_id == org_id, Workflow.id == workflow_id)
    if lock:
        query = query.with_for_update()
    workflow = session.scalar(query)
    if workflow is None:
        raise DomainError(404, "not_found", "Workflow not found")
    return workflow


def run_for(session: Session, org_id: str, run_id: str, lock: bool = False) -> Run:
    query = select(Run).where(Run.org_id == org_id, Run.id == run_id)
    if lock:
        query = query.with_for_update()
    run = session.scalar(query)
    if run is None:
        raise DomainError(404, "not_found", "Execution not found")
    return run


def create_workflow(session: Session, vault: Vault, org_id: str, actor_id: str, project_id: str, name: str, description: str, definition: Definition, environment: str = "development") -> tuple[Workflow, str]:
    project = session.scalar(select(Project).where(Project.org_id == org_id, Project.id == project_id))
    if project is None:
        raise DomainError(404, "not_found", "Project not found")
    workflow_id, signing_key = new_id(), secrets.token_urlsafe(32)
    workflow = Workflow(id=workflow_id, org_id=org_id, project_id=project_id, name=name, description=description, draft=definition.model_dump(), environment=environment, webhook_cipher=vault.seal(signing_key, f"webhook:{org_id}:{workflow_id}"))
    session.add(workflow)
    session.flush()
    audit(session, org_id, actor_id, "workflow.created", workflow.id)
    return workflow, signing_key


def save_draft(session: Session, org_id: str, actor_id: str, workflow_id: str, definition: Definition, expected_revision: int, name: str | None = None, description: str | None = None, max_concurrency: int | None = None) -> Workflow:
    workflow = workflow_for(session, org_id, workflow_id, lock=True)
    if workflow.draft_revision != expected_revision:
        raise DomainError(409, "revision_conflict", "This draft changed. Reload before saving.")
    workflow.draft = definition.model_dump()
    workflow.draft_revision += 1
    workflow.updated_at = time.time()
    if name is not None:
        workflow.name = name
    if description is not None:
        workflow.description = description
    if max_concurrency is not None:
        workflow.max_concurrency = max_concurrency
    audit(session, org_id, actor_id, "workflow.updated", workflow.id, revision=workflow.draft_revision)
    return workflow


def publish(session: Session, org_id: str, actor_id: str, workflow_id: str, expected_revision: int) -> WorkflowVersion:
    workflow = workflow_for(session, org_id, workflow_id, lock=True)
    if workflow.draft_revision != expected_revision:
        raise DomainError(409, "revision_conflict", "Reload the workflow before publishing")
    definition = Definition.model_validate(workflow.draft)
    validate_credentials(session, org_id, workflow.project_id, definition)
    number = (session.scalar(select(func.max(WorkflowVersion.number)).where(WorkflowVersion.workflow_id == workflow.id)) or 0) + 1
    version = WorkflowVersion(workflow_id=workflow.id, number=number, definition=definition.model_dump(), digest=json_digest(definition.model_dump()), created_by=actor_id)
    session.add(version)
    workflow.published_version = number
    workflow.updated_at = time.time()
    workflow.archived = False
    session.flush()
    audit(session, org_id, actor_id, "workflow.published", workflow.id, version=number)
    return version


def validate_credentials(session: Session, org_id: str, project_id: str, definition: Definition) -> dict[str, int]:
    versions = {}
    for node in definition.nodes:
        credential_id = getattr(node, "credential_id", None)
        if not credential_id:
            continue
        credential = session.scalar(select(Credential).where(Credential.org_id == org_id, Credential.project_id == project_id, Credential.id == credential_id, Credential.revoked.is_(False)))
        if credential is None:
            raise DomainError(422, "credential_unavailable", f"Credential unavailable for node {node.id}")
        provider = getattr(node, "provider", None)
        if provider and provider != credential.kind:
            raise DomainError(422, "credential_kind", f"Wrong credential kind for node {node.id}")
        if node.type == "http" and credential.kind != "http":
            raise DomainError(422, "credential_kind", "HTTP nodes require an HTTP credential")
        versions[credential.id] = credential.current_version
    return versions


def enqueue(session: Session, vault: Vault, org_id: str, actor_id: str | None, workflow_id: str, payload: dict, idempotency_key: str, max_queued: int, dry_run: bool = False, source: str = "manual", version_id: str | None = None, parent_id: str | None = None) -> tuple[Run, bool]:
    workflow = workflow_for(session, org_id, workflow_id, lock=True)
    if len(json.dumps(payload).encode()) > 65536:
        raise DomainError(413, "input_too_large", "Execution input exceeds 64 KiB")
    request_hash = json_digest({"payload": payload, "dry_run": dry_run, "version_id": version_id})
    existing = session.scalar(select(Run).where(Run.org_id == org_id, Run.workflow_id == workflow_id, Run.idempotency_key == idempotency_key))
    if existing:
        if existing.input_hash != request_hash:
            raise DomainError(409, "idempotency_conflict", "This key was already used with different input")
        return existing, False
    if workflow.archived:
        raise DomainError(409, "workflow_archived", "Archived workflows cannot receive executions")
    query = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
    query = query.where(WorkflowVersion.id == version_id) if version_id else query.where(WorkflowVersion.number == workflow.published_version)
    version = session.scalar(query)
    if version is None:
        raise DomainError(409, "not_published", "Publish a version before running this workflow")
    definition = Definition.model_validate(version.definition)
    errors = list(Draft202012Validator(definition.input_schema).iter_errors(payload))
    if errors:
        raise DomainError(422, "input_schema", "Input does not match the workflow schema")
    credentials = validate_credentials(session, org_id, workflow.project_id, definition)
    # Locking the organization serializes admission across different workflows.
    from flowpilot.models import Organization
    session.scalar(select(Organization).where(Organization.id == org_id).with_for_update())
    pending = session.scalar(select(func.count()).select_from(Run).where(Run.org_id == org_id, Run.status.not_in(TERMINAL_RUNS))) or 0
    if pending >= max_queued:
        raise DomainError(429, "queue_full", "Workspace execution capacity reached")
    run_id = new_id()
    run = Run(id=run_id, org_id=org_id, workflow_id=workflow_id, version_id=version.id, idempotency_key=idempotency_key, input_hash=request_hash, input_cipher=vault.seal(payload, f"input:{org_id}:{run_id}"), credentials=credentials, dry_run=dry_run, source=source, parent_id=parent_id, available_at=current_time(session))
    session.add(run)
    session.flush()
    for node in definition.nodes:
        session.add(StepRun(run_id=run_id, node_id=node.id, kind=node.type))
    audit(session, org_id, actor_id, "run.created", run_id, source=source, dry_run=dry_run)
    return run, True


def credential_values(session: Session, vault: Vault, org_id: str) -> tuple[str, ...]:
    query = select(CredentialVersion, Credential).join(Credential, Credential.id == CredentialVersion.credential_id).where(Credential.org_id == org_id)
    values = []
    for revision, credential in session.execute(query):
        context = f"credential:{org_id}:{credential.id}:{revision.number}"
        values.append(vault.open(revision.ciphertext, context))
    return tuple(values)


def get_credential(session: Session, vault: Vault, run: Run, credential_id: str) -> tuple[Credential, str]:
    credential = session.scalar(select(Credential).where(Credential.id == credential_id, Credential.org_id == run.org_id, Credential.revoked.is_(False)))
    number = run.credentials.get(credential_id)
    if credential is None or number is None:
        raise DomainError(409, "credential_revoked", "Credential is no longer available")
    revision = session.get(CredentialVersion, (credential_id, number))
    if revision is None:
        raise DomainError(409, "credential_unavailable", "Credential version is not available")
    value = vault.open(revision.ciphertext, f"credential:{run.org_id}:{credential_id}:{number}")
    return credential, value
