"""Run the portable checks without claiming unavailable environment tests."""
import compileall
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    output = ROOT / 'verification'
    output.mkdir(exist_ok=True)
    environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
    npm = 'npm.cmd' if os.name == 'nt' else 'npm'
    commands = [
        [sys.executable, '-m', 'pytest', '-q', '--junitxml=verification/backend-junit.xml', '--cov=flowpilot', '--cov-report=json:verification/coverage.json', '--cov-report=term-missing'],
        [npm, 'run', 'typecheck'],
        [npm, 'run', 'build'],
        [npm, 'test'],
    ]
    results = []
    for command in commands:
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout)
        name = 'backend' if 'pytest' in command else command[-1]
        (output / f'{name}.txt').write_text(result.stdout)
        results.append({'command': command, 'returncode': result.returncode, 'seconds': round(time.perf_counter() - started, 3)})
        if result.returncode:
            (output / 'checks.json').write_text(json.dumps(results, indent=2) + '\n')
            raise SystemExit(result.returncode)
    for directory in ['src', 'scripts', 'tests', 'migrations']:
        if not compileall.compile_dir(str(ROOT / directory), quiet=1):
            raise SystemExit('Python syntax compilation failed')
    (output / 'checks.json').write_text(json.dumps(results, indent=2) + '\n')
    print('Portable checks passed. PostgreSQL skips and browser limitations remain explicit.')


if __name__ == '__main__':
    main()
