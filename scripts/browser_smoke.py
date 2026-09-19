"""Exercise the shipped console against a real API and temporary database."""
import argparse
import base64
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from flowpilot.api.app import create_app
from flowpilot.cli import migrate, seed_demo
from flowpilot.config import Settings
from flowpilot.db import Database
from flowpilot.engine.worker import Worker


def script_bundle(directory):
    subprocess.run(['tsc', '-p', str(ROOT / 'web/tsconfig.json'), '--module', 'commonjs', '--moduleResolution', 'node', '--verbatimModuleSyntax', 'false', '--outDir', str(directory)], check=True, cwd=ROOT)
    modules = []
    for path in sorted(directory.glob('*.js')):
        modules.append(f'{json.dumps(path.stem)}: function(require, module, exports) {{\n{path.read_text()}\n}}')
    return '''(() => {
const factories = {''' + ',\n'.join(modules) + r'''};
const cache = {};
function require(name) {
  const key = name.replace(/^\.\//, '').replace(/\.js$/, '');
  if (!cache[key]) {
    const module = {exports: {}};
    cache[key] = module;
    factories[key](require, module, module.exports);
  }
  return cache[key].exports;
}
require('app');
})();'''


def smoke(page, email, password, screenshots):
    checks = []
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.get_by_label('Email address').fill(email)
    page.get_by_label('Password', exact=True).fill(password)
    page.get_by_role('button', name='Sign in', exact=True).click()
    expect(page.get_by_role('heading', name='Execution overview', exact=True)).to_be_visible()
    checks.append('Sign in and load workspace overview')
    if screenshots:
        page.screenshot(path=str(screenshots / 'overview.png'), full_page=True)
    page.get_by_role('link', name='Workflows', exact=True).click()
    expect(page.get_by_role('heading', name='Workflows', exact=True)).to_be_visible()
    expect(page.locator('.workflow-card')).to_have_count(3)
    page.get_by_label('Search workflows').fill('Lead')
    expect(page.locator('.workflow-card')).to_have_count(1)
    page.get_by_label('Search workflows').fill('')
    checks.append('Navigate and filter workflows')
    if screenshots:
        page.screenshot(path=str(screenshots / 'workflows.png'), full_page=True)
    page.get_by_role('link', name='Lead triage', exact=True).click()
    expect(page.get_by_label('Workflow JSON definition')).to_be_visible()
    page.get_by_role('button', name='Validate', exact=True).click()
    expect(page.get_by_text('Definition is valid', exact=True)).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / 'workflow.png'), full_page=True)
    checks.append('Render dependency graph and validate a definition')
    page.get_by_role('link', name='Overview', exact=True).click()
    page.locator('.attention-link').filter(has_text='Lead triage').click()
    expect(page.get_by_role('button', name='Approve and continue', exact=True)).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / 'execution.png'), full_page=True)
    page.get_by_role('button', name='Approve and continue', exact=True).click()
    expect(page.locator('.execution-meta').get_by_text('Succeeded', exact=True)).to_be_visible(timeout=15000)
    checks.append('Approve a durable wait and complete an execution')
    page.get_by_role('button', name='Replay', exact=True).click()
    page.get_by_role('button', name='Create replay', exact=True).click()
    expect(page.locator('.execution-meta').get_by_text('Dry run', exact=True)).to_be_visible(timeout=10000)
    checks.append('Create an explicitly marked dry replay')
    page.get_by_role('link', name='Workflows', exact=True).click()
    page.get_by_role('button', name='New workflow', exact=True).click()
    page.get_by_label('Starting point', exact=True).select_option(label='Lead triage')
    page.get_by_label('Workflow name', exact=True).fill('Browser integration workflow')
    page.get_by_role('button', name='Create workflow', exact=True).click()
    page.get_by_role('button', name='I have saved it', exact=True).click()
    expect(page.get_by_role('heading', name='Browser integration workflow', exact=True)).to_be_visible()
    page.get_by_role('button', name='Publish version', exact=True).click()
    expect(page.get_by_text('v1', exact=True)).to_be_visible()
    page.get_by_role('button', name='Run', exact=True).click()
    page.get_by_role('button', name='Start execution', exact=True).click()
    expect(page.locator('.execution-meta')).to_be_visible()
    checks.append('Create, publish and run a workflow through the UI')
    page.get_by_role('button', name='Cancel execution', exact=True).click()
    expect(page.locator('.execution-meta').get_by_text('Cancelled', exact=True)).to_be_visible(timeout=10000)
    checks.append('Cancel a pending execution')
    page.get_by_role('link', name='Credentials', exact=True).click()
    expect(page.get_by_role('heading', name='Credential vault', exact=True)).to_be_visible()
    page.get_by_role('button', name='Add credential', exact=True).click()
    page.get_by_label('Name', exact=True).fill('Browser test key')
    page.get_by_label('Provider', exact=True).select_option('anthropic')
    page.get_by_label('Secret value', exact=True).fill('test-only-key-not-a-live-secret')
    page.get_by_role('button', name='Save credential', exact=True).click()
    expect(page.get_by_role('heading', name='Browser test key', exact=True)).to_be_visible()
    assert 'test-only-key-not-a-live-secret' not in page.locator('body').inner_text()
    checks.append('Create a credential without exposing plaintext in the console')
    page.get_by_role('button', name='Rotate', exact=True).click()
    page.get_by_label('New secret', exact=True).fill('test-only-rotated-key-not-a-live-secret')
    page.get_by_role('button', name='Save new version', exact=True).click()
    expect(page.get_by_text('Anthropic · Version 2', exact=True)).to_be_visible()
    checks.append('Rotate a credential and display its new version')
    page.get_by_role('button', name='Revoke', exact=True).click()
    expect(page.get_by_text('Revoked', exact=True)).to_be_visible()
    checks.append('Revoke a credential through the console')
    page.get_by_role('link', name='Workspace', exact=True).click()
    expect(page.get_by_role('heading', name='Workspace', exact=True)).to_be_visible()
    page.get_by_role('button', name='Add project', exact=True).click()
    page.get_by_label('Name', exact=True).fill('Browser test project')
    page.get_by_role('button', name='Create project', exact=True).click()
    expect(page.get_by_text('Browser test project', exact=True)).to_be_visible()
    checks.append('Create a project and inspect the workspace audit trail')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('link', name='Overview', exact=True).click()
    expect(page.get_by_role('heading', name='Execution overview', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'Mobile page overflow'
    if screenshots:
        page.screenshot(path=str(screenshots / 'mobile.png'), full_page=True)
    checks.append('Render at 390px without page-level horizontal overflow')
    page.get_by_role('button', name='Sign out', exact=True).click()
    expect(page.get_by_role('button', name='Sign in', exact=True)).to_be_visible()
    checks.append('Sign out and return to the sign-in form')
    assert not errors, errors
    checks.append('No uncaught JavaScript errors')
    return checks


@contextmanager
def local_server(settings, directory, base_url):
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "FLOWPILOT_ENVIRONMENT": "test",
        "FLOWPILOT_DATABASE_URL": settings.database_url,
        "FLOWPILOT_MASTER_KEYS": settings.master_keys.get_secret_value(),
        "FLOWPILOT_PUBLIC_ORIGIN": base_url,
        "FLOWPILOT_ALLOWED_HOSTS": '["127.0.0.1","localhost"]',
        "FLOWPILOT_EGRESS_HOSTS": '[]',
        "FLOWPILOT_SECURE_COOKIES": "false",
        "FLOWPILOT_STATIC_DIR": str(ROOT / "web/dist"),
    }
    port = base_url.rsplit(":", 1)[1]
    with (directory / "server.log").open("w") as log:
        processes = [
            subprocess.Popen([sys.executable, "-m", "uvicorn", "flowpilot.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", port], env=environment, cwd=ROOT, stdout=log, stderr=log),
            subprocess.Popen([sys.executable, "-m", "flowpilot.engine.worker"], env=environment, cwd=ROOT, stdout=log, stderr=log),
        ]
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base_url + "/health/ready", timeout=1) as result:
                        if result.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Isolated application did not become ready")
            yield
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bridge', action='store_true', help='Render without browser navigation; bridge fetch to FastAPI TestClient')
    parser.add_argument('--base-url', help='Existing disposable demo; requires BROWSER_TEST_EMAIL and BROWSER_TEST_PASSWORD')
    parser.add_argument('--chromium', default=None)
    parser.add_argument('--screenshots', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'verification/browser.json')
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        password = secrets.token_urlsafe(20)
        settings = Settings(environment='test', database_url=f'sqlite:///{directory / "browser.db"}', master_keys=json.dumps({'v1': base64.urlsafe_b64encode(os.urandom(32)).decode()}), public_origin='http://testserver', allowed_hosts=['testserver'], static_dir=ROOT / 'web/dist')
        migrate(settings.database_url)
        db = Database(settings.database_url)
        os.environ['FLOWPILOT_DEMO_PASSWORD'] = password
        os.environ['FLOWPILOT_DEMO_EMAIL'] = 'browser@flowpilot.local'
        seed_demo(db, settings)
        worker = Worker(db, settings, worker_id='browser-test-worker')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            base_url = f'http://127.0.0.1:{probe.getsockname()[1]}'
        server = nullcontext() if args.bridge or args.base_url else local_server(settings, directory, base_url)
        with server, TestClient(create_app(settings, db)) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1020}, device_scale_factor=1)
            page.set_default_timeout(10000)
            page.on('dialog', lambda dialog: dialog.accept())
            if args.bridge:
                def fetch(payload):
                    path = payload['url']
                    if not path.startswith('/api/v1/'):
                        raise ValueError('The test bridge only reaches the local API')
                    result = client.request(payload['method'], path, headers={**payload['headers'], 'Origin': 'http://testserver'}, content=payload.get('body'))
                    for _ in range(30):
                        if not worker.tick():
                            break
                    return {'status': result.status_code, 'body': result.text, 'csrf': client.cookies.get('fp_csrf', '')}
                page.expose_function('localApi', fetch)
                page.set_content('<div id="app"></div><div id="dialogs"></div><div id="toasts" role="status" aria-live="polite"></div>')
                page.add_style_tag(content=(ROOT / 'web/dist/styles.css').read_text())
                page.evaluate('''() => {
 const stored = new Map();
 Object.defineProperty(window, 'sessionStorage', {value: {getItem: k => stored.get(k) ?? null, setItem: (k,v) => stored.set(k,v)}});
 let csrf = '';
 Object.defineProperty(document, 'cookie', {get: () => csrf ? 'fp_csrf=' + csrf : ''});
 if (!crypto.randomUUID) crypto.randomUUID = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {const r=crypto.getRandomValues(new Uint8Array(1))[0] & 15; return (c === 'x' ? r : (r & 3) | 8).toString(16);});
 window.fetch = async (url, init = {}) => {
  const result = await window.localApi({url: String(url), method: init.method ?? 'GET', headers: Object.fromEntries(new Headers(init.headers)), body: init.body});
  csrf = result.csrf;
  return new Response(result.status === 204 ? null : result.body, {status: result.status, headers: {'content-type': 'application/json'}});
 };
}''')
                page.add_script_tag(content=script_bundle(directory / 'compiled'))
                email = 'browser@flowpilot.local'
            else:
                email = 'browser@flowpilot.local'
                if args.base_url:
                    email = os.environ.get('BROWSER_TEST_EMAIL', '')
                    password = os.environ.get('BROWSER_TEST_PASSWORD', '')
                    if not email or not password:
                        raise ValueError('An existing demo requires BROWSER_TEST_EMAIL and BROWSER_TEST_PASSWORD')
                page.goto(args.base_url or base_url)
            checks = smoke(page, email, password, args.screenshots)
            browser.close()
        worker.tracer_provider.shutdown()
        db.engine.dispose()
    result = {'status': 'passed', 'mode': 'DOM + real API bridge' if args.bridge else 'HTTP end-to-end', 'checks': checks, 'count': len(checks), 'notes': 'Bridge mode does not test browser cookies, CSP, networking or native module delivery. These need the HTTP mode.' if args.bridge else ''}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
