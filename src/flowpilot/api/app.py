import hmac
import json
import math
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from flowpilot.api.auth import (
    Actor,
    DUMMY_HASH,
    actor,
    administrator,
    memberships_for,
    session_user,
    throttle,
    verify_password,
    writer,
)
from flowpilot.api.schemas import (
    ActivateVersion,
    Approval,
    CredentialCreate,
    CredentialRotate,
    DraftUpdate,
    Login,
    MemberUpdate,
    ProjectCreate,
    Publish,
    Replay,
    RunCreate,
    WorkflowCreate,
)
from flowpilot.config import Settings, get_settings
from flowpilot.crypto import Vault, digest, redact
from flowpilot.db import Database
from flowpilot.engine.definition import Definition
from flowpilot.errors import DomainError
from flowpilot.models import (
    Attempt,
    AuditEvent,
    AuthSession,
    Credential,
    CredentialVersion,
    Membership,
    Project,
    Run,
    StepRun,
    User,
    WorkerHeartbeat,
    Workflow,
    WorkflowVersion,
    new_id,
)
from flowpilot.services import (
    TERMINAL_RUNS,
    audit,
    create_workflow,
    credential_values,
    enqueue,
    publish,
    run_for,
    save_draft,
    workflow_for,
)
from flowpilot.telemetry import build_tracer, log_event


class BodyLimit:
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                response = JSONResponse({"error": {"code": "body_too_large", "detail": "Request body exceeds the configured limit"}}, status_code=413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        depth, quoted, escaped = 0, False, False
        for byte in body:
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte in (91, 123):
                depth += 1
                if depth > 48:
                    response = JSONResponse({"error": {"code": "body_too_deep", "detail": "Request nesting limit reached"}}, status_code=413)
                    return await response(scope, receive, send)
            elif byte in (93, 125):
                depth -= 1
        if body and any(key == b"content-type" and b"application/json" in value for key, value in scope.get("headers", [])):
            def finite_float(value):
                result = float(value)
                if not math.isfinite(result):
                    raise ValueError("Non-finite JSON number")
                return result

            def reject_constant(value):
                raise ValueError("Non-standard JSON constant")

            try:
                json.loads(body, parse_float=finite_float, parse_constant=reject_constant)
            except (ValueError, UnicodeDecodeError):
                response = JSONResponse({"error": {"code": "invalid_json", "detail": "Request body must contain valid finite JSON"}}, status_code=400)
                return await response(scope, receive, send)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)


def workflow_json(row: Workflow) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description, "project_id": row.project_id, "environment": row.environment, "draft_revision": row.draft_revision, "published_version": row.published_version, "archived": row.archived, "max_concurrency": row.max_concurrency, "created_at": row.created_at, "updated_at": row.updated_at}


def run_json(row: Run, name: str = "", number: int | None = None) -> dict:
    return {"id": row.id, "workflow_id": row.workflow_id, "workflow_name": name, "version": number, "status": row.status, "dry_run": row.dry_run, "source": row.source, "parent_id": row.parent_id, "created_at": row.created_at, "started_at": row.started_at, "finished_at": row.finished_at, "error_code": row.error_code, "trace_id": row.trace_id, "available_at": row.available_at}


def credential_json(row: Credential) -> dict:
    return {"id": row.id, "name": row.name, "kind": row.kind, "project_id": row.project_id, "allowed_host": row.allowed_host, "version": row.current_version, "revoked": row.revoked, "created_at": row.created_at}


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or Database(settings.database_url)
    vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
    tracer_provider, tracer = build_tracer(settings.otlp_endpoint)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        tracer_provider.shutdown()

    app = FastAPI(title="FlowPilot API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs" if settings.environment != "production" else None, openapi_url="/api/openapi.json", redoc_url=None)
    app.state.db = db
    app.state.settings = settings
    app.state.vault = vault
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(BodyLimit, limit=settings.max_request_bytes)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        return JSONResponse({"error": {"code": error.code, "detail": error.detail, "request_id": getattr(request.state, "request_id", None)}}, status_code=error.status, headers={"Retry-After": "60"} if error.status == 429 else {})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({"error": {"code": "validation_failed", "detail": "Check the submitted fields", "fields": [{"path": ".".join(map(str, item["loc"])), "type": item["type"]} for item in error.errors()]}}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, _error: IntegrityError):
        return JSONResponse({"error": {"code": "conflict", "detail": "A record with these identifiers already exists"}}, status_code=409)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        log_event("api.unhandled_error", request_id=getattr(request.state, "request_id", None), error_type=type(error).__name__)
        return JSONResponse({"error": {"code": "internal_error", "detail": "The request could not be completed"}}, status_code=500)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        started = time.monotonic()
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not request.url.path.startswith("/api/v1/hooks/"):
            if origin and origin != settings.public_origin:
                return JSONResponse({"error": {"code": "origin_denied", "detail": "Origin not allowed"}}, status_code=403)
        with tracer.start_as_current_span("http.request", attributes={"http.request.method": request.method}):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        route = request.scope.get("route")
        log_event("http.completed", request_id=request.state.request_id, method=request.method, route=getattr(route, "path", "unmatched"), status=response.status_code, duration_ms=round((time.monotonic() - started) * 1000, 2))
        return response

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/health/ready", tags=["Health"])
    def ready():
        try:
            with db.sessions() as session:
                revision = session.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != "0001":
                    raise DomainError(503, "migration_required", "Database migration required")
        except SQLAlchemyError as error:
            raise DomainError(503, "database_unavailable", "Database is not ready") from error
        return {"status": "ready", "database": db.engine.dialect.name}

    @app.post("/api/v1/auth/login", tags=["Authentication"])
    def login(body: Login, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        with db.transaction() as session:
            by_ip = throttle(session, f"login-ip:{digest(ip)[:32]}", 25, 300)
            by_email = throttle(session, f"login-email:{digest(body.email)[:32]}", 10, 300)
        if not by_ip or not by_email:
            raise DomainError(429, "rate_limited", "Too many sign-in attempts. Try again later.")
        with db.transaction() as session:
            user = session.scalar(select(User).where(User.email == body.email))
            valid = verify_password(body.password.get_secret_value(), user.password_hash if user else DUMMY_HASH)
            if not user or not valid or user.disabled:
                raise DomainError(401, "invalid_credentials", "Email or password is incorrect")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            session.add(AuthSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), expires_at=time.time() + settings.session_hours * 3600))
            memberships = memberships_for(session, user.id)
            result = {"id": user.id, "name": user.name, "email": user.email, "workspaces": memberships}
        response.set_cookie("fp_session", token, max_age=settings.session_hours * 3600, httponly=True, secure=settings.secure_cookies, samesite="strict", path="/")
        response.set_cookie("fp_csrf", csrf, max_age=settings.session_hours * 3600, httponly=False, secure=settings.secure_cookies, samesite="strict", path="/")
        return result

    @app.get("/api/v1/auth/me", tags=["Authentication"])
    def me(request: Request):
        user = session_user(request)
        with db.sessions() as session:
            return {"id": user.id, "name": user.name, "email": user.email, "workspaces": memberships_for(session, user.id)}

    @app.post("/api/v1/auth/logout", status_code=204, tags=["Authentication"])
    def logout(request: Request, response: Response):
        session_user(request)
        with db.transaction() as session:
            session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get("fp_session", ""))))
        response.delete_cookie("fp_session", path="/")
        response.delete_cookie("fp_csrf", path="/")

    @app.get("/api/v1/projects", tags=["Workspace"])
    def projects(current: Actor = Depends(actor)):
        with db.sessions() as session:
            return {"items": [{"id": row.id, "name": row.name} for row in session.scalars(select(Project).where(Project.org_id == current.org_id).order_by(Project.name))]}

    @app.post("/api/v1/projects", status_code=201, tags=["Workspace"])
    def add_project(body: ProjectCreate, current: Actor = Depends(administrator)):
        with db.transaction() as session:
            project = Project(org_id=current.org_id, name=body.name)
            session.add(project)
            session.flush()
            audit(session, current.org_id, current.id, "project.created", project.id)
            return {"id": project.id, "name": project.name}

    @app.get("/api/v1/workflows", tags=["Workflows"])
    def workflows(current: Actor = Depends(actor), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        with db.sessions() as session:
            query = select(Workflow).where(Workflow.org_id == current.org_id)
            count = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(query.order_by(Workflow.updated_at.desc(), Workflow.id).offset(offset).limit(limit))
            return {"items": [workflow_json(row) for row in rows], "total": count}

    @app.post("/api/v1/workflows", status_code=201, tags=["Workflows"])
    def add_workflow(body: WorkflowCreate, current: Actor = Depends(writer)):
        with db.transaction() as session:
            workflow, signing_key = create_workflow(session, vault, current.org_id, current.id, body.project_id, body.name, body.description, body.definition, body.environment)
            return {**workflow_json(workflow), "webhook_secret": signing_key}

    @app.post("/api/v1/definitions/validate", tags=["Workflows"])
    def validate_definition(body: Definition, _current: Actor = Depends(writer)):
        return {"valid": True, "nodes": len(body.nodes), "definition": body.model_dump()}

    @app.get("/api/v1/definitions/schema", tags=["Workflows"])
    def definition_schema(_current: Actor = Depends(actor)):
        return Definition.model_json_schema()

    @app.get("/api/v1/workflows/{workflow_id}", tags=["Workflows"])
    def get_workflow(workflow_id: str, current: Actor = Depends(actor)):
        with db.sessions() as session:
            workflow = workflow_for(session, current.org_id, workflow_id)
            versions = session.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id).order_by(WorkflowVersion.number.desc()))
            return {**workflow_json(workflow), "definition": workflow.draft, "versions": [{"id": item.id, "number": item.number, "digest": item.digest, "created_at": item.created_at} for item in versions], "webhook_path": f"/api/v1/hooks/{workflow.id}"}

    @app.patch("/api/v1/workflows/{workflow_id}", tags=["Workflows"])
    def edit_workflow(workflow_id: str, body: DraftUpdate, current: Actor = Depends(writer)):
        with db.transaction() as session:
            workflow = save_draft(session, current.org_id, current.id, workflow_id, body.definition, body.expected_revision, body.name, body.description, body.max_concurrency)
            return workflow_json(workflow)

    @app.post("/api/v1/workflows/{workflow_id}/publish", status_code=201, tags=["Workflows"])
    def publish_workflow(workflow_id: str, body: Publish, current: Actor = Depends(writer)):
        with db.transaction() as session:
            version = publish(session, current.org_id, current.id, workflow_id, body.expected_revision)
            return {"number": version.number, "digest": version.digest, "id": version.id}

    @app.post("/api/v1/workflows/{workflow_id}/activate", tags=["Workflows"])
    def activate_version(workflow_id: str, body: ActivateVersion, current: Actor = Depends(writer)):
        with db.transaction() as session:
            workflow = workflow_for(session, current.org_id, workflow_id, lock=True)
            version = session.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.number == body.number))
            if not version:
                raise DomainError(404, "not_found", "Version not found")
            workflow.published_version = body.number
            audit(session, current.org_id, current.id, "workflow.activated", workflow.id, version=body.number)
            return workflow_json(workflow)

    @app.post("/api/v1/workflows/{workflow_id}/rotate-webhook", tags=["Workflows"])
    def rotate_webhook(workflow_id: str, current: Actor = Depends(administrator)):
        with db.transaction() as session:
            workflow = workflow_for(session, current.org_id, workflow_id, lock=True)
            key = secrets.token_urlsafe(32)
            workflow.webhook_cipher = vault.seal(key, f"webhook:{current.org_id}:{workflow.id}")
            audit(session, current.org_id, current.id, "workflow.webhook_rotated", workflow.id)
            return {"webhook_secret": key}

    @app.post("/api/v1/workflows/{workflow_id}/runs", status_code=202, tags=["Executions"])
    def start_run(workflow_id: str, body: RunCreate, response: Response, current: Actor = Depends(writer), idempotency_key: Annotated[str | None, Header(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")] = None):
        if not idempotency_key:
            raise DomainError(400, "idempotency_required", "An Idempotency-Key header is required")
        with db.transaction() as session:
            run, created = enqueue(session, vault, current.org_id, current.id, workflow_id, body.input, idempotency_key, settings.max_queued_runs, body.dry_run)
            response.status_code = 202 if created else 200
            return run_json(run)

    @app.post("/api/v1/hooks/{workflow_id}", status_code=202, tags=["Webhooks"])
    async def hook(workflow_id: str, request: Request, response: Response):
        body = await request.body()
        timestamp = request.headers.get("x-flowpilot-timestamp", "")
        event_id = request.headers.get("x-flowpilot-event-id", "")
        signature = request.headers.get("x-flowpilot-signature", "")
        if not timestamp.isdigit() or len(timestamp) > 12 or not 1 <= len(event_id) <= 100 or any(not (char.isalnum() or char in "_.:-") for char in event_id):
            raise DomainError(401, "signature_invalid", "Webhook authentication failed")
        if abs(time.time() - int(timestamp)) > settings.webhook_clock_skew:
            raise DomainError(401, "signature_expired", "Webhook timestamp is outside the allowed window")
        with db.sessions() as session:
            workflow = session.get(Workflow, workflow_id)
            if not workflow:
                raise DomainError(401, "signature_invalid", "Webhook authentication failed")
            key = vault.open(workflow.webhook_cipher, f"webhook:{workflow.org_id}:{workflow.id}")
            org_id = workflow.org_id
        expected = hmac.new(key.encode(), timestamp.encode() + b"." + event_id.encode() + b"." + body, "sha256").hexdigest()
        if not hmac.compare_digest("sha256=" + expected, signature):
            raise DomainError(401, "signature_invalid", "Webhook authentication failed")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise DomainError(400, "json_invalid", "Expected JSON input") from error
        if not isinstance(payload, dict):
            raise DomainError(422, "input_schema", "Webhook input must be an object")
        with db.transaction() as session:
            allowed = throttle(session, f"hook:{workflow_id}", 120, 60)
        if not allowed:
            raise DomainError(429, "rate_limited", "Webhook rate limit reached")
        with db.transaction() as session:
            run, created = enqueue(session, vault, org_id, None, workflow_id, payload, f"hook:{event_id}", settings.max_queued_runs, source="webhook")
            response.status_code = 202 if created else 200
            return {"id": run.id, "status": run.status, "duplicate": not created}

    @app.get("/api/v1/runs", tags=["Executions"])
    def runs(current: Actor = Depends(actor), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), status: str | None = None, workflow_id: str | None = None):
        with db.sessions() as session:
            query = select(Run, Workflow.name, WorkflowVersion.number).join(Workflow, Run.workflow_id == Workflow.id).join(WorkflowVersion, Run.version_id == WorkflowVersion.id).where(Run.org_id == current.org_id)
            if status:
                query = query.where(Run.status == status)
            if workflow_id:
                query = query.where(Run.workflow_id == workflow_id)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.execute(query.order_by(Run.created_at.desc(), Run.id).offset(offset).limit(limit))
            return {"items": [run_json(row, name, number) for row, name, number in rows], "total": total}

    @app.get("/api/v1/runs/{run_id}", tags=["Executions"])
    def get_run(run_id: str, current: Actor = Depends(actor)):
        with db.sessions() as session:
            run = run_for(session, current.org_id, run_id)
            workflow = workflow_for(session, current.org_id, run.workflow_id)
            version = session.get(WorkflowVersion, run.version_id)
            values = credential_values(session, vault, current.org_id)
            steps = {row.node_id: row for row in session.scalars(select(StepRun).where(StepRun.run_id == run.id))}
            output = []
            for node in version.definition["nodes"]:
                step = steps[node["id"]]
                data = vault.open(step.output_cipher, f"output:{run.org_id}:{run.id}:{step.node_id}") if step.output_cipher else None
                attempts = session.scalars(select(Attempt).where(Attempt.run_id == run.id, Attempt.node_id == step.node_id).order_by(Attempt.number))
                output.append({"id": step.node_id, "type": step.kind, "label": node.get("label") or step.node_id, "status": step.status, "duration_ms": step.duration_ms, "error_code": step.error_code, "output": redact(data, values), "usage": step.usage, "ready_at": step.ready_at, "approval_message": node.get("message"), "attempts": [{"number": item.number, "status": item.status, "error_code": item.error_code, "duration_ms": item.duration_ms, "started_at": item.started_at} for item in attempts]})
            payload = vault.open(run.input_cipher, f"input:{run.org_id}:{run.id}")
            return {**run_json(run, workflow.name, version.number), "input": redact(payload, values), "steps": output}

    @app.post("/api/v1/runs/{run_id}/cancel", tags=["Executions"])
    def cancel_run(run_id: str, current: Actor = Depends(writer)):
        with db.transaction() as session:
            run = run_for(session, current.org_id, run_id, lock=True)
            if run.status not in TERMINAL_RUNS:
                run.status = "cancelled"
                run.finished_at = time.time()
                run.lease_token = None
                run.lease_until = None
                session.execute(update(StepRun).where(StepRun.run_id == run.id, StepRun.status.not_in(["succeeded", "skipped", "failed"])).values(status="cancelled"))
                session.execute(update(Attempt).where(Attempt.run_id == run.id, Attempt.status == "running").values(status="cancelled", finished_at=time.time()))
                audit(session, current.org_id, current.id, "run.cancelled", run.id)
            return run_json(run)

    @app.post("/api/v1/runs/{run_id}/replay", status_code=202, tags=["Executions"])
    def replay_run(run_id: str, body: Replay, current: Actor = Depends(writer)):
        if not body.dry_run and not body.acknowledge_side_effects:
            raise DomainError(422, "replay_confirmation", "Confirm that replay may repeat external side effects")
        with db.transaction() as session:
            run = run_for(session, current.org_id, run_id)
            payload = vault.open(run.input_cipher, f"input:{run.org_id}:{run.id}")
            replayed, _ = enqueue(session, vault, current.org_id, current.id, run.workflow_id, payload, f"replay:{new_id()}", settings.max_queued_runs, body.dry_run, "replay", run.version_id, run.id)
            return run_json(replayed)

    @app.post("/api/v1/runs/{run_id}/steps/{node_id}/approval", tags=["Executions"])
    def approve_step(run_id: str, node_id: str, body: Approval, current: Actor = Depends(writer)):
        with db.transaction() as session:
            run = run_for(session, current.org_id, run_id, lock=True)
            step = session.get(StepRun, (run.id, node_id))
            if run.status in TERMINAL_RUNS or not step or step.status != "awaiting_approval" or not step.ready_at or step.ready_at < time.time():
                raise DomainError(409, "approval_unavailable", "This execution is not awaiting this approval")
            step.output_cipher = vault.seal({"approved": body.approved, "reviewer": current.id, "note": body.note}, f"output:{run.org_id}:{run.id}:{node_id}")
            step.status = "succeeded" if body.approved else "failed"
            run.status = "queued" if body.approved else "failed"
            run.available_at = time.time()
            if not body.approved:
                run.finished_at = time.time()
                run.error_code = step.error_code = "approval_rejected"
            audit(session, current.org_id, current.id, "run.approval", run.id, node_id=node_id, approved=body.approved)
            return run_json(run)

    @app.get("/api/v1/credentials", tags=["Credentials"])
    def credentials(current: Actor = Depends(actor)):
        with db.sessions() as session:
            return {"items": [credential_json(row) for row in session.scalars(select(Credential).where(Credential.org_id == current.org_id).order_by(Credential.created_at.desc()))]}

    @app.post("/api/v1/credentials", status_code=201, tags=["Credentials"])
    def add_credential(body: CredentialCreate, current: Actor = Depends(administrator)):
        if body.kind == "http" and body.allowed_host not in settings.egress_hosts:
            raise DomainError(422, "host_denied", "HTTP credentials must be bound to an allowed egress host")
        with db.transaction() as session:
            project = session.scalar(select(Project).where(Project.id == body.project_id, Project.org_id == current.org_id))
            if not project:
                raise DomainError(404, "not_found", "Project not found")
            value = Credential(id=new_id(), org_id=current.org_id, project_id=body.project_id, name=body.name, kind=body.kind, allowed_host=body.allowed_host)
            session.add(value)
            session.flush()
            cipher = vault.seal(body.value.get_secret_value(), f"credential:{current.org_id}:{value.id}:1")
            session.add(CredentialVersion(credential_id=value.id, number=1, ciphertext=cipher))
            audit(session, current.org_id, current.id, "credential.created", value.id, kind=value.kind)
            return credential_json(value)

    @app.post("/api/v1/credentials/{credential_id}/rotate", tags=["Credentials"])
    def rotate_credential(credential_id: str, body: CredentialRotate, current: Actor = Depends(administrator)):
        with db.transaction() as session:
            credential = session.scalar(select(Credential).where(Credential.id == credential_id, Credential.org_id == current.org_id).with_for_update())
            if not credential or credential.revoked:
                raise DomainError(404, "not_found", "Credential not found")
            credential.current_version += 1
            cipher = vault.seal(body.value.get_secret_value(), f"credential:{current.org_id}:{credential.id}:{credential.current_version}")
            session.add(CredentialVersion(credential_id=credential.id, number=credential.current_version, ciphertext=cipher))
            audit(session, current.org_id, current.id, "credential.rotated", credential.id, version=credential.current_version)
            return credential_json(credential)

    @app.post("/api/v1/credentials/{credential_id}/revoke", tags=["Credentials"])
    def revoke_credential(credential_id: str, current: Actor = Depends(administrator)):
        with db.transaction() as session:
            credential = session.scalar(select(Credential).where(Credential.id == credential_id, Credential.org_id == current.org_id).with_for_update())
            if not credential:
                raise DomainError(404, "not_found", "Credential not found")
            credential.revoked = True
            audit(session, current.org_id, current.id, "credential.revoked", credential.id)
            return credential_json(credential)

    @app.get("/api/v1/workspace", tags=["Workspace"])
    def workspace(current: Actor = Depends(actor)):
        with db.sessions() as session:
            members = session.execute(select(Membership, User).join(User, Membership.user_id == User.id).where(Membership.org_id == current.org_id))
            events = session.scalars(select(AuditEvent).where(AuditEvent.org_id == current.org_id).order_by(AuditEvent.created_at.desc()).limit(50))
            workers = session.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.seen_at > time.time() - 120))
            return {"members": [{"id": user.id, "name": user.name, "email": user.email, "role": membership.role} for membership, user in members], "events": [{"id": event.id, "action": event.action, "resource_id": event.resource_id, "created_at": event.created_at, "actor_id": event.actor_id, "detail": event.detail} for event in events], "workers": [{"id": worker.id, "seen_at": worker.seen_at} for worker in workers], "environment": settings.environment, "database": db.engine.dialect.name, "egress_hosts": settings.egress_hosts, "retention_days": settings.retention_days}

    @app.post("/api/v1/members", tags=["Workspace"])
    def add_member(body: MemberUpdate, current: Actor = Depends(administrator)):
        with db.transaction() as session:
            user = session.scalar(select(User).where(User.email == body.email.strip().lower()))
            if not user:
                raise DomainError(404, "user_not_found", "An operator must create this user with the CLI first")
            membership = session.get(Membership, (current.org_id, user.id))
            if membership and (membership.role == "owner" or user.id == current.id):
                raise DomainError(409, "owner_protected", "This membership cannot be changed here")
            if membership:
                membership.role = body.role
            else:
                session.add(Membership(org_id=current.org_id, user_id=user.id, role=body.role))
            audit(session, current.org_id, current.id, "member.updated", user.id, role=body.role)
            return {"id": user.id, "role": body.role}

    @app.get("/api/v1/overview", tags=["Observability"])
    def overview(current: Actor = Depends(actor)):
        now = time.time()
        since = now - 7 * 86400
        with db.sessions() as session:
            counts = dict(session.execute(select(Run.status, func.count()).where(Run.org_id == current.org_id, Run.created_at >= since).group_by(Run.status)).all())
            workflow_count = session.scalar(select(func.count()).select_from(Workflow).where(Workflow.org_id == current.org_id)) or 0
            recent = session.execute(select(Run, Workflow.name, WorkflowVersion.number).join(Workflow, Run.workflow_id == Workflow.id).join(WorkflowVersion, Run.version_id == WorkflowVersion.id).where(Run.org_id == current.org_id).order_by(Run.created_at.desc()).limit(8)).all()
            day_start = int(now // 86400) * 86400
            activity = []
            for day in range(6, -1, -1):
                start = day_start - day * 86400
                daily = dict(session.execute(select(Run.status, func.count()).where(Run.org_id == current.org_id, Run.created_at >= start, Run.created_at < start + 86400).group_by(Run.status)).all())
                activity.append({"date": start, "total": sum(daily.values()), "succeeded": daily.get("succeeded", 0), "failed": daily.get("failed", 0)})
            closed = counts.get("succeeded", 0) + counts.get("failed", 0)
            simulated = session.scalar(select(func.count()).select_from(Run).where(Run.org_id == current.org_id, Run.created_at >= since, Run.dry_run.is_(True))) or 0
            return {"workflow_count": workflow_count, "counts": counts, "total": sum(counts.values()), "success_rate": round(counts.get("succeeded", 0) / closed * 100, 1) if closed else None, "dry_runs": simulated, "activity": activity, "recent": [run_json(run, name, number) for run, name, number in recent], "window_days": 7}

    @app.get("/metrics", tags=["Observability"])
    def metrics(request: Request):
        expected = settings.metrics_token.get_secret_value()
        if not expected or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {expected}"):
            raise DomainError(401, "authentication_required", "Metrics token required")
        with db.sessions() as session:
            counts = session.execute(select(Run.status, func.count()).group_by(Run.status)).all()
            workers = session.scalar(select(func.count()).select_from(WorkerHeartbeat).where(WorkerHeartbeat.seen_at >= time.time() - 120)) or 0
            lines = ["# HELP flowpilot_runs Persisted executions by current status.", "# TYPE flowpilot_runs gauge"]
            lines.extend(f'flowpilot_runs{{status="{status}"}} {count}' for status, count in counts)
            lines.extend(["# HELP flowpilot_workers_active Workers seen in the past 120 seconds.", "# TYPE flowpilot_workers_active gauge", f"flowpilot_workers_active {workers}"])
            return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        if path.startswith(("api/", "health/")):
            raise DomainError(404, "not_found", "Endpoint not found")
        base = settings.static_dir.resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            raise DomainError(404, "not_found", "File not found")
        if target.is_file():
            return FileResponse(target)
        if path and "." in path.split("/")[-1]:
            raise DomainError(404, "not_found", "File not found")
        index = base / "index.html"
        if not index.exists():
            raise DomainError(503, "frontend_missing", "Build the web console first")
        return FileResponse(index)

    return app
