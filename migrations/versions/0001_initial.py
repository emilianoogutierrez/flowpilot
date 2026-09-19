"""Initial control plane and execution schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('organizations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('rate_buckets',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('window_start', sa.Float(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('disabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('worker_heartbeats',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('seen_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('resource_id', sa.String(length=100), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_org_id'), 'audit_events', ['org_id'], unique=False)
    op.create_table('auth_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('csrf_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_auth_sessions_expires_at'), 'auth_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'], unique=False)
    op.create_table('memberships',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('org_id', 'user_id')
    )
    op.create_table('projects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_project_name')
    )
    op.create_index(op.f('ix_projects_org_id'), 'projects', ['org_id'], unique=False)
    op.create_table('credentials',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('allowed_host', sa.String(length=253), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'project_id', 'name', name='uq_credential_name')
    )
    op.create_index(op.f('ix_credentials_org_id'), 'credentials', ['org_id'], unique=False)
    op.create_table('workflows',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('environment', sa.String(length=20), nullable=False),
    sa.Column('draft', sa.JSON(), nullable=False),
    sa.Column('draft_revision', sa.Integer(), nullable=False),
    sa.Column('published_version', sa.Integer(), nullable=True),
    sa.Column('webhook_cipher', sa.Text(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('max_concurrency', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflows_org_id'), 'workflows', ['org_id'], unique=False)
    op.create_table('credential_versions',
    sa.Column('credential_id', sa.String(length=36), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('ciphertext', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['credential_id'], ['credentials.id'], ),
    sa.PrimaryKeyConstraint('credential_id', 'number')
    )
    op.create_table('workflow_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('workflow_id', sa.String(length=36), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('definition', sa.JSON(), nullable=False),
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'number', name='uq_workflow_version')
    )
    op.create_index(op.f('ix_workflow_versions_workflow_id'), 'workflow_versions', ['workflow_id'], unique=False)
    op.create_table('runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('workflow_id', sa.String(length=36), nullable=False),
    sa.Column('version_id', sa.String(length=36), nullable=False),
    sa.Column('idempotency_key', sa.String(length=140), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('input_cipher', sa.Text(), nullable=False),
    sa.Column('credentials', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=24), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('available_at', sa.Float(), nullable=False),
    sa.Column('lease_until', sa.Float(), nullable=True),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('worker_id', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('started_at', sa.Float(), nullable=True),
    sa.Column('finished_at', sa.Float(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'workflow_id', 'idempotency_key', name='uq_run_idempotency')
    )
    op.create_index('ix_runs_claim', 'runs', ['status', 'available_at', 'lease_until'], unique=False)
    op.create_index(op.f('ix_runs_org_id'), 'runs', ['org_id'], unique=False)
    op.create_index(op.f('ix_runs_status'), 'runs', ['status'], unique=False)
    op.create_index(op.f('ix_runs_workflow_id'), 'runs', ['workflow_id'], unique=False)
    op.create_table('attempts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('node_id', sa.String(length=60), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('lease_token', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('started_at', sa.Float(), nullable=False),
    sa.Column('finished_at', sa.Float(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'node_id', 'number', name='uq_attempt_number')
    )
    op.create_index(op.f('ix_attempts_run_id'), 'attempts', ['run_id'], unique=False)
    op.create_table('step_runs',
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('node_id', sa.String(length=60), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('output_cipher', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('ready_at', sa.Float(), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=False),
    sa.Column('usage', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'node_id')
    )


def downgrade():
    op.drop_table('step_runs')
    op.drop_index(op.f('ix_attempts_run_id'), table_name='attempts')
    op.drop_table('attempts')
    op.drop_index(op.f('ix_runs_workflow_id'), table_name='runs')
    op.drop_index(op.f('ix_runs_status'), table_name='runs')
    op.drop_index(op.f('ix_runs_org_id'), table_name='runs')
    op.drop_index('ix_runs_claim', table_name='runs')
    op.drop_table('runs')
    op.drop_index(op.f('ix_workflow_versions_workflow_id'), table_name='workflow_versions')
    op.drop_table('workflow_versions')
    op.drop_table('credential_versions')
    op.drop_index(op.f('ix_workflows_org_id'), table_name='workflows')
    op.drop_table('workflows')
    op.drop_index(op.f('ix_credentials_org_id'), table_name='credentials')
    op.drop_table('credentials')
    op.drop_index(op.f('ix_projects_org_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_auth_sessions_user_id'), table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_expires_at'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index(op.f('ix_audit_events_org_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_table('worker_heartbeats')
    op.drop_table('users')
    op.drop_table('rate_buckets')
    op.drop_table('organizations')
