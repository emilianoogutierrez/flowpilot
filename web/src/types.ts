export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Role = 'owner' | 'admin' | 'developer' | 'viewer';
export interface Workspace { id: string; name: string; role: Role }
export interface User { id: string; name: string; email: string; workspaces: Workspace[] }
export interface Project { id: string; name: string }
export interface WorkflowNode {
  id: string;
  type: 'set' | 'condition' | 'delay' | 'approval' | 'http' | 'ai';
  label?: string;
  depends_on?: string[];
  [key: string]: unknown;
}
export interface Definition { schema_version: 1; input_schema: Record<string, unknown>; nodes: WorkflowNode[] }
export interface Version { id: string; number: number; digest: string; created_at: number }
export interface Workflow {
  id: string; name: string; description: string; project_id: string;
  environment: string; draft_revision: number; published_version: number | null;
  archived: boolean; max_concurrency: number; created_at: number; updated_at: number;
  definition: Definition; versions: Version[]; webhook_path: string;
}
export interface Run {
  id: string; workflow_id: string; workflow_name: string; version: number;
  status: string; dry_run: boolean; source: string; parent_id: string | null;
  created_at: number; started_at: number | null; finished_at: number | null;
  available_at: number; error_code: string | null; trace_id: string;
}
export interface Attempt { number: number; status: string; error_code: string | null; duration_ms: number | null; started_at: number }
export interface Step {
  id: string; type: string; label: string; status: string; duration_ms: number;
  error_code: string | null; output: Json; usage: Record<string, Json>;
  ready_at: number | null; approval_message: string | null; attempts: Attempt[];
}
export interface RunDetail extends Run { input: Json; steps: Step[] }
export interface Collection<T> { items: T[]; total: number }
export interface Overview {
  workflow_count: number; counts: Record<string, number>; total: number;
  success_rate: number | null; dry_runs: number; window_days: number;
  activity: { date: number; total: number; succeeded: number; failed: number }[];
  recent: Run[];
}
export interface Credential {
  id: string; name: string; project_id: string; kind: string; version: number;
  allowed_host: string; revoked: boolean; created_at: number;
}
export interface WorkspaceDetail {
  members: { id: string; name: string; email: string; role: Role }[];
  events: { id: string; action: string; resource_id: string; actor_id: string | null; created_at: number; detail: Json }[];
  workers: { id: string; seen_at: number }[];
  environment: string; database: string; egress_hosts: string[]; retention_days: number;
}
