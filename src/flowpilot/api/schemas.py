from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator

from flowpilot.engine.definition import Definition, StrictModel


class Login(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)


class WorkflowCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    project_id: str
    environment: Literal["development", "staging", "production"] = "development"
    definition: Definition


class DraftUpdate(StrictModel):
    definition: Definition
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    max_concurrency: int | None = Field(default=None, ge=1, le=16)


class Publish(StrictModel):
    expected_revision: int = Field(ge=1)


class ActivateVersion(StrictModel):
    number: int = Field(ge=1)


class RunCreate(StrictModel):
    input: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class Replay(StrictModel):
    acknowledge_side_effects: bool = False
    dry_run: bool = True


class Approval(StrictModel):
    approved: bool
    note: str = Field(default="", max_length=300)


class CredentialCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    project_id: str
    kind: Literal["http", "openai", "anthropic", "gemini"]
    value: SecretStr = Field(min_length=8, max_length=4096)
    allowed_host: str = Field(default="", max_length=253)


class CredentialRotate(StrictModel):
    value: SecretStr = Field(min_length=8, max_length=4096)


class MemberUpdate(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["admin", "developer", "viewer"]
