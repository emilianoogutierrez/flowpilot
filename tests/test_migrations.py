from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from flowpilot.models import Base


def test_schema_matches_models(db):
    with db.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def test_migration_can_downgrade_and_upgrade(db, settings):
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    config.attributes['database_url'] = settings.database_url
    command.downgrade(config, 'base')
    assert inspect(db.engine).get_table_names() == ['alembic_version']
    command.upgrade(config, 'head')
    assert 'runs' in inspect(db.engine).get_table_names()
