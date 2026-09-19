"""Regenerate public contracts without real credentials or a persistent database."""
import base64
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from flowpilot.api.app import create_app
from flowpilot.config import Settings
from flowpilot.db import Database
from flowpilot.engine.definition import Definition

settings = Settings(environment='test', database_url='sqlite:///:memory:', master_keys=json.dumps({'v1': base64.urlsafe_b64encode(os.urandom(32)).decode()}))
database = Database(settings.database_url)
application = create_app(settings, database)
for name, document in [('workflow-schema.json', Definition.model_json_schema()), ('openapi.json', application.openapi())]:
    (ROOT / 'docs' / name).write_text(json.dumps(document, indent=2) + '\n')
database.engine.dispose()
print('Public API and workflow contracts exported.')
