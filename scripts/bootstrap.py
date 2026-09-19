import base64
import json
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; nothing was overwritten.")
else:
    password = secrets.token_urlsafe(18)
    keys = json.dumps({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()})
    content = f'''FLOWPILOT_ENVIRONMENT=development
FLOWPILOT_DATABASE_URL=sqlite:///./var/flowpilot.db
FLOWPILOT_MASTER_KEYS='{keys}'
FLOWPILOT_ACTIVE_KEY_ID=v1
FLOWPILOT_PUBLIC_ORIGIN=http://localhost:8000
FLOWPILOT_ALLOWED_HOSTS='["localhost","127.0.0.1"]'
FLOWPILOT_EGRESS_HOSTS='[]'
FLOWPILOT_SECURE_COOKIES=false
FLOWPILOT_METRICS_TOKEN={secrets.token_urlsafe(32)}
FLOWPILOT_DEMO_EMAIL=demo@flowpilot.local
FLOWPILOT_DEMO_PASSWORD={password}
POSTGRES_PASSWORD={secrets.token_urlsafe(24)}
'''
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    print("Created .env with random keys. Keep this file private.")
    print("Demo email: demo@flowpilot.local")
    print(f"Demo password: {password}")
