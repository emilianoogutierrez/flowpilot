export class ApiError extends Error {
  constructor(public status: number, public code: string, detail: string) {
    super(detail);
  }
}

let workspace = sessionStorage.getItem('flowpilot.workspace') ?? '';

export function setWorkspace(value: string): void {
  workspace = value;
  sessionStorage.setItem('flowpilot.workspace', value);
}

export function getWorkspace(): string {
  return workspace;
}

function csrfToken(): string {
  return document.cookie.split('; ').find(cookie => cookie.startsWith('fp_csrf='))?.split('=')[1] ?? '';
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('X-Workspace-ID', workspace);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken());
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check that the API is running.');
  }
  if (response.status === 204) return undefined as T;
  const payload = await response.json() as { error?: { code: string; detail: string; fields?: { path: string; type: string }[] } };
  if (!response.ok) {
    const field = payload.error?.fields?.[0];
    const detail = (payload.error?.detail ?? `Request failed (${response.status})`) + (field ? `: ${field.path} (${field.type})` : '');
    throw new ApiError(response.status, payload.error?.code ?? 'request_failed', detail);
  }
  return payload as T;
}

export function post<T>(path: string, body: unknown = {}, headers?: HeadersInit): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body), headers });
}
