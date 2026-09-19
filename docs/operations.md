# Operations

## Before accepting real events

Provision non-demo accounts, correct allowed hosts and origin, HTTPS, secure cookies and a protected PostgreSQL database. Test a backup and restore together with the relevant encryption keys. Configure allowed egress hosts and document receiver-side idempotency. Do not run a public demo with a shared password.

## Health and monitoring

Liveness proves the HTTP process can answer. Readiness proves database access and the expected migration. Workspace heartbeats show recently polling workers. Prometheus text metrics expose global run-state counts, worker counts and queue age, not customer payloads.

Logs contain event names, IDs, durations and stable error codes. They intentionally avoid prompts, response bodies and credentials. Optional OpenTelemetry spans cover API requests and step execution. Full cross-process parent propagation is not implemented; run IDs correlate the records. Do not describe the current setup as a complete distributed trace.

## A stuck run

Inspect its state, next eligible time, lease expiry, attempts and current node. A durable delay or approval is not a stuck worker. After worker death, safe work can be recovered after the lease expires. Unsafe HTTP work may stop as `outcome_unknown`.

Investigate the external receiver before replaying uncertain work. A cancelled run cannot commit further progress, but cancellation cannot unsend an HTTP request or cancel a provider bill.

## Rotating a credential

Rotate a credential in the console or API. New runs pin the new version; existing runs keep the old one. Revoke the credential to block subsequent access to any version. If an actual secret leaked, rotate it at the provider as well. Application-side revision changes do not revoke an external API key.

## Rotating master keys

Back up the database and existing key map securely. Add a new random key ID to `FLOWPILOT_MASTER_KEYS` without deleting the old key. Set `FLOWPILOT_ACTIVE_KEY_ID` to the new ID on all processes. Stop workers and apply the change in a controlled maintenance window.

```bash
python -m flowpilot.cli rotate-master-key
```

The command rewraps stored data keys in one transaction. Review completion, restart processes and verify representative reads. Retain old master keys as long as corresponding backups exist. This implementation is appropriate for a small installation; large data volumes need a staged rewrap design.

## Retention

```bash
python -m flowpilot.cli purge
```

The command deletes terminal executions older than the configured cutoff, their steps/attempts, expired sessions and stale rate buckets. It does not run automatically. Audit events, credential history and external backups have separate retention responsibilities.

Deletion also removes the run's idempotency record. A sufficiently old repeated event can be accepted again after purge. Use a longer deduplication ledger if your sender's replay horizon requires one.

## Backup and restore

Use database-native consistent backups. Store master keys separately with restricted access. A database backup without the relevant keys cannot decrypt inputs, outputs or credentials. A leaked backup plus keys exposes those values.

A PostgreSQL restore rehearsal is deployment-specific. Complete and record one against the actual backup process before relying on recoverability.

## Releases

Stop admission or route traffic away during incompatible migration changes. Apply migrations once in a separate init job, not concurrently in every API worker. Deploy API and workers from the same revision. Check readiness, run a synthetic workflow, inspect an approval flow and verify signing after rollout.

Do not update dependencies or container images blindly. Record and rerun the verification commands after changes.
