import argparse
import getpass
import json
import os

import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import delete, select

from flowpilot.api.auth import PASSWORDS
from flowpilot.config import get_settings
from flowpilot.crypto import Vault
from flowpilot.db import Database
from flowpilot.engine.definition import Definition
from flowpilot.engine.worker import Worker
from flowpilot.models import (
    AuthSession,
    CredentialVersion,
    Membership,
    Organization,
    Project,
    RateBucket,
    Run,
    User,
    Workflow,
    new_id,
)
from flowpilot.services import TERMINAL_RUNS, create_workflow, enqueue, publish

ROOT = Path(__file__).resolve().parents[2]


def migrate(url: str):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def create_user(db: Database, email: str, name: str, password: str, organization: str | None = None) -> dict:
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters")
    with db.transaction() as session:
        existing = session.scalar(select(User).where(User.email == email.strip().lower()))
        if existing:
            raise ValueError("This user already exists")
        user = User(id=new_id(), email=email.strip().lower(), name=name, password_hash=PASSWORDS.hash(password))
        session.add(user)
        session.flush()
        result = {"user_id": user.id}
        if organization:
            org = Organization(id=new_id(), name=organization)
            session.add(org)
            session.flush()
            session.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
            project = Project(id=new_id(), org_id=org.id, name="Default")
            session.add(project)
            session.flush()
            result.update(org_id=org.id, project_id=project.id)
        return result


def seed_demo(db: Database, settings):
    if settings.environment == "production":
        raise ValueError("Demo provisioning is disabled in production")
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    email = env.get("FLOWPILOT_DEMO_EMAIL", "demo@flowpilot.local")
    password = env.get("FLOWPILOT_DEMO_PASSWORD")
    if not password or len(password) < 12:
        raise ValueError("Run scripts/bootstrap.py before provisioning the demo")
    with db.sessions() as session:
        if session.scalar(select(User).where(User.email == email)):
            print("Demo already exists. Existing data was not changed.")
            return
    ids = create_user(db, email, "Demo User", password, "Demo Workspace")
    vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
    templates = [("Lead triage", "Classify inquiries and require an operator's approval.", "lead-triage.json"), ("Event normalization", "Validate and map incoming events into a stable contract.", "normalize-event.json"), ("Reviewed delivery", "An explicit approval before sending data to an external service.", "http-delivery.json")]
    workflows = []
    with db.transaction() as session:
        for name, description, filename in templates:
            definition = Definition.model_validate_json((ROOT / "examples" / filename).read_text())
            workflow, _ = create_workflow(session, vault, ids["org_id"], ids["user_id"], ids["project_id"], name, description, definition)
            if filename != "http-delivery.json":
                publish(session, ids["org_id"], ids["user_id"], workflow.id, 1)
            workflows.append(workflow.id)
        for index in range(6):
            enqueue(session, vault, ids["org_id"], ids["user_id"], workflows[1], {"name": f"Sample event {index + 1}", "amount": 1200 + index * 300}, f"demo:{index}", settings.max_queued_runs, source="demo")
        enqueue(session, vault, ids["org_id"], ids["user_id"], workflows[0], {"company": "Example Studio", "message": "Connect our support form to our internal tools.", "budget": 12000}, "demo:lead", settings.max_queued_runs, source="demo")
    worker = Worker(db, settings, worker_id="demo-provisioner")
    for _ in range(100):
        if not worker.tick():
            break
    worker.tracer_provider.shutdown()
    print(f"Demo provisioned for {email}. Executions were run locally; AI uses the explicit fixture provider.")


def main():
    parser = argparse.ArgumentParser(prog="flowpilot")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--demo", action="store_true")
    commands.add_parser("worker")
    user = commands.add_parser("create-user")
    user.add_argument("email")
    user.add_argument("--name", required=True)
    user.add_argument("--organization")
    password = commands.add_parser("reset-password")
    password.add_argument("email")
    validate = commands.add_parser("validate")
    validate.add_argument("file", type=Path)
    commands.add_parser("export-schema")
    commands.add_parser("purge")
    commands.add_parser("rotate-master-key")
    args = parser.parse_args()
    if args.command == "validate":
        definition = Definition.model_validate_json(args.file.read_text())
        print(f"Valid workflow. {len(definition.nodes)} nodes.")
        return
    if args.command == "export-schema":
        print(json.dumps(Definition.model_json_schema(), indent=2))
        return
    settings = get_settings()
    if args.command == "worker":
        from flowpilot.engine.worker import main as run_worker
        run_worker()
        return

    db = Database(settings.database_url)
    try:
        if args.command == "init":
            migrate(settings.database_url)
            if args.demo:
                seed_demo(db, settings)
        elif args.command == "create-user":
            value = getpass.getpass("Password (at least 12 characters): ")
            print(json.dumps(create_user(db, args.email, args.name, value, args.organization)))
        elif args.command == "reset-password":
            value = getpass.getpass("New password (at least 12 characters): ")
            if len(value) < 12:
                raise ValueError("Password is too short")
            with db.transaction() as session:
                user = session.scalar(select(User).where(User.email == args.email.strip().lower()))
                if not user:
                    raise ValueError("User not found")
                user.password_hash = PASSWORDS.hash(value)
                session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            print("Password changed. Existing sessions were revoked.")
        elif args.command == "purge":
            cutoff = time.time() - settings.retention_days * 86400
            with db.transaction() as session:
                expired = session.execute(delete(Run).where(Run.status.in_(TERMINAL_RUNS), Run.finished_at < cutoff))
                session.execute(delete(AuthSession).where(AuthSession.expires_at < time.time()))
                session.execute(delete(RateBucket).where(RateBucket.window_start < time.time() - 86400))
                print(f"Removed {expired.rowcount} expired executions. Audit events were retained.")
        elif args.command == "rotate-master-key":
            vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
            with db.transaction() as session:
                for revision in session.scalars(select(CredentialVersion)):
                    from flowpilot.models import Credential
                    credential = session.get(Credential, revision.credential_id)
                    revision.ciphertext = vault.rewrap(revision.ciphertext, f"credential:{credential.org_id}:{credential.id}:{revision.number}")
                for workflow in session.scalars(select(Workflow)):
                    workflow.webhook_cipher = vault.rewrap(workflow.webhook_cipher, f"webhook:{workflow.org_id}:{workflow.id}")
                from flowpilot.models import StepRun
                for run in session.scalars(select(Run)):
                    run.input_cipher = vault.rewrap(run.input_cipher, f"input:{run.org_id}:{run.id}")
                    for step in session.scalars(select(StepRun).where(StepRun.run_id == run.id, StepRun.output_cipher.is_not(None))):
                        step.output_cipher = vault.rewrap(step.output_cipher, f"output:{run.org_id}:{run.id}:{step.node_id}")
            print("Stored envelopes now use the active wrapping key. Keep old keys for existing backups.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
