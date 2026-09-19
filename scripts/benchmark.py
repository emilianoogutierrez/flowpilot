"""Measure a bounded, local workload; no remote integrations or claimed scale."""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sqlalchemy import select

from flowpilot.cli import create_user, migrate
from flowpilot.config import Settings
from flowpilot.crypto import Vault
from flowpilot.db import Database
from flowpilot.engine.definition import Definition
from flowpilot.engine.worker import Worker
from flowpilot.models import Run
from flowpilot.services import create_workflow, enqueue, publish


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=100)
    parser.add_argument('--output', type=Path, default=ROOT / 'verification/benchmark.json')
    args = parser.parse_args()
    if not 1 <= args.runs <= 1000:
        raise SystemExit('Use 1 to 1000 runs for this local benchmark')
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(environment='test', database_url=f'sqlite:///{Path(directory) / "bench.db"}', master_keys=json.dumps({'v1': base64.urlsafe_b64encode(os.urandom(32)).decode()}))
        migrate(settings.database_url)
        db = Database(settings.database_url)
        vault = Vault(settings.master_keys.get_secret_value(), settings.active_key_id)
        ids = create_user(db, 'bench@example.test', 'Benchmark', 'temporary-benchmark-password', 'Benchmark')
        definition = Definition.model_validate_json((ROOT / 'examples/normalize-event.json').read_text())
        with db.transaction() as session:
            workflow, _ = create_workflow(session, vault, ids['org_id'], ids['user_id'], ids['project_id'], 'Local normalization benchmark', '', definition)
            publish(session, ids['org_id'], ids['user_id'], workflow.id, 1)
            workflow_id = workflow.id
        admitted = time.perf_counter()
        with db.transaction() as session:
            for index in range(args.runs):
                enqueue(session, vault, ids['org_id'], ids['user_id'], workflow_id, {'name': 'Synthetic event', 'amount': 100}, f'benchmark-{index}', args.runs + 1, source='benchmark')
        admission_seconds = time.perf_counter() - admitted
        worker = Worker(db, settings, worker_id='benchmark-worker')
        started = time.perf_counter()
        ticks = 0
        while worker.tick():
            ticks += 1
            if ticks > args.runs * 10:
                raise RuntimeError('Unexpected benchmark execution loop')
        elapsed = time.perf_counter() - started
        with db.sessions() as session:
            runs = session.scalars(select(Run)).all()
            if not all(run.status == 'succeeded' for run in runs):
                raise RuntimeError('A benchmark execution failed')
            latencies = [(run.finished_at - run.created_at) * 1000 for run in runs]
        worker.tracer_provider.shutdown()
        db.engine.dispose()
    result = {
        'workload': 'SQLite, one worker, pre-admitted runs, three local nodes, no network',
        'runs': args.runs,
        'nodes_per_run': len(definition.nodes),
        'worker_ticks': ticks,
        'admission_seconds': round(admission_seconds, 4),
        'queue_drain_seconds': round(elapsed, 4),
        'completed_runs_per_second': round(args.runs / elapsed, 2),
        'latency_including_queue_ms': {'p50': round(statistics.median(latencies), 2), 'p95': round(percentile(latencies, .95), 2), 'p99': round(percentile(latencies, .99), 2)},
        'environment': {'python': platform.python_version(), 'os': platform.system(), 'machine': platform.machine(), 'logical_cpus_visible': os.cpu_count()},
        'interpretation': 'Local smoke benchmark only. Does not estimate PostgreSQL capacity, real API latency or AI throughput.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
