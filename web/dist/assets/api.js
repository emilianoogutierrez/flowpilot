export class ApiError extends Error {
    status;
    code;
    constructor(status, code, detail) {
        super(detail);
        this.status = status;
        this.code = code;
    }
}
let workspace = sessionStorage.getItem('flowpilot.workspace') ?? '';
export function setWorkspace(value) {
    workspace = value;
    sessionStorage.setItem('flowpilot.workspace', value);
}
export function getWorkspace() {
    return workspace;
}
function csrfToken() {
    return document.cookie.split('; ').find(cookie => cookie.startsWith('fp_csrf='))?.split('=')[1] ?? '';
}
export async function api(path, options = {}) {
    const headers = new Headers(options.headers);
    headers.set('X-Workspace-ID', workspace);
    if (options.body)
        headers.set('Content-Type', 'application/json');
    if (options.method && options.method !== 'GET')
        headers.set('X-CSRF-Token', csrfToken());
    let response;
    try {
        response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'same-origin' });
    }
    catch {
        throw new ApiError(0, 'network_error', 'Cannot reach the server. Check that the API is running.');
    }
    if (response.status === 204)
        return undefined;
    const payload = await response.json();
    if (!response.ok) {
        const field = payload.error?.fields?.[0];
        const detail = (payload.error?.detail ?? `Request failed (${response.status})`) + (field ? `: ${field.path} (${field.type})` : '');
        throw new ApiError(response.status, payload.error?.code ?? 'request_failed', detail);
    }
    return payload;
}
export function post(path, body = {}, headers) {
    return api(path, { method: 'POST', body: JSON.stringify(body), headers });
}
//# sourceMappingURL=api.js.map