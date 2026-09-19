"""Submit one signed event to a loopback development instance."""
import argparse
import hmac
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('workflow_id', type=uuid.UUID)
parser.add_argument('input', type=Path)
parser.add_argument('--base-url', default='http://localhost:8000')
parser.add_argument('--event-id', default=None)
args = parser.parse_args()
base = urlsplit(args.base_url)
if base.scheme not in {'http', 'https'} or base.hostname not in {'localhost', '127.0.0.1', '::1'} or base.username or base.password or base.query or base.fragment:
    raise SystemExit('This helper only submits to a loopback development server')
secret = os.environ.get('FLOWPILOT_WEBHOOK_SECRET')
if not secret:
    raise SystemExit('Set FLOWPILOT_WEBHOOK_SECRET locally; do not paste it into source code')
body = args.input.read_bytes()
json.loads(body)
stamp = str(int(time.time()))
event_id = args.event_id or str(uuid.uuid4())
signature = hmac.new(secret.encode(), stamp.encode() + b'.' + event_id.encode() + b'.' + body, 'sha256').hexdigest()
request = urllib.request.Request(args.base_url.rstrip('/') + f'/api/v1/hooks/{args.workflow_id}', data=body, method='POST', headers={
    'Content-Type': 'application/json',
    'X-FlowPilot-Timestamp': stamp,
    'X-FlowPilot-Event-ID': event_id,
    'X-FlowPilot-Signature': 'sha256=' + signature,
})
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.status, response.read(4096).decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read(4096).decode())
    raise SystemExit(1)
