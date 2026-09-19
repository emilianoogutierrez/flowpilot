import os
from pathlib import Path

import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
os.chdir(root)
env = {**os.environ, "PYTHONPATH": str(root / "src")}
subprocess.run([sys.executable, "scripts/bootstrap.py"], check=True, env=env)
subprocess.run([sys.executable, "-m", "flowpilot.cli", "init", "--demo"], check=True, env=env)
commands = [
    [sys.executable, "-m", "uvicorn", "flowpilot.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000"],
    [sys.executable, "-m", "flowpilot.engine.worker"],
]
processes = [subprocess.Popen(command, env=env) for command in commands]
print("FlowPilot is starting at http://localhost:8000. Press Ctrl+C to stop.")
try:
    while all(process.poll() is None for process in processes):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
