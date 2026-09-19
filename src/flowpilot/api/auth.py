import hmac
import math
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flowpilot.crypto import digest
from flowpilot.errors import DomainError
from flowpilot.models import AuthSession, Membership, Organization, RateBucket, User

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(24))


@dataclass(frozen=True)
class Actor:
    id: str
    name: str
    email: str
    org_id: str
    role: str


def throttle(session, key: str, limit: int, seconds: int, now: float | None = None):
    now = time.time() if now is None else now
    start = math.floor(now / seconds) * seconds
    bucket_key = f"{key}:{start}"
    insert = sqlite_insert if session.bind.dialect.name == "sqlite" else pg_insert
    statement = insert(RateBucket).values(key=bucket_key, window_start=start, count=1)
    statement = statement.on_conflict_do_update(index_elements=[RateBucket.key], set_={"count": RateBucket.count + 1}).returning(RateBucket.count)
    count = session.scalar(statement)
    return count <= limit


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORDS.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def session_user(request: Request) -> User:
    token = request.cookies.get("fp_session", "")
    if not token or len(token) > 128:
        raise DomainError(401, "authentication_required", "Sign in to continue")
    with request.app.state.db.sessions() as session:
        record = session.get(AuthSession, digest(token))
        user = session.get(User, record.user_id) if record else None
        if not record or record.expires_at <= time.time() or not user or user.disabled:
            raise DomainError(401, "session_expired", "Your session expired. Sign in again.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("x-csrf-token", "")
            if not csrf or not hmac.compare_digest(digest(csrf), record.csrf_hash):
                raise DomainError(403, "csrf_invalid", "The request could not be verified")
        session.expunge(user)
        return user


def actor(request: Request) -> Actor:
    user = session_user(request)
    org_id = request.headers.get("x-workspace-id", "")
    with request.app.state.db.transaction() as session:
        membership = session.get(Membership, (org_id, user.id))
        if membership is None:
            raise DomainError(403, "workspace_access_denied", "Workspace access denied")
        permitted = throttle(session, f"api:{user.id}", 180, 60)
        role = membership.role
    if not permitted:
        raise DomainError(429, "rate_limited", "Too many requests. Try again shortly.")
    return Actor(user.id, user.name, user.email, org_id, role)


def writer(request: Request) -> Actor:
    value = actor(request)
    if value.role not in {"owner", "admin", "developer"}:
        raise DomainError(403, "permission_denied", "This action requires developer access")
    return value


def administrator(request: Request) -> Actor:
    value = actor(request)
    if value.role not in {"owner", "admin"}:
        raise DomainError(403, "permission_denied", "This action requires administrator access")
    return value


def memberships_for(session, user_id: str) -> list[dict]:
    rows = session.execute(select(Membership, Organization).join(Organization, Membership.org_id == Organization.id).where(Membership.user_id == user_id))
    return [{"id": org.id, "name": org.name, "role": membership.role} for membership, org in rows]
