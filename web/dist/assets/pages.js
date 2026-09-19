import { api, getWorkspace, post } from './api.js';
import { duration, initials, label, timestamp } from './format.js';
import { templates } from './templates.js';
import { badge, busy, button, copy, el, empty, field, graph, icon, input, jsonView, modal, select, textArea, toast } from './ui.js';
export const navigation = [
    { path: 'overview', label: 'Overview', icon: 'grid' },
    { path: 'workflows', label: 'Workflows', icon: 'workflow' },
    { path: 'runs', label: 'Executions', icon: 'runs' },
    { path: 'credentials', label: 'Credentials', icon: 'key' },
    { path: 'workspace', label: 'Workspace', icon: 'team' },
];
export function navigate(path) {
    location.hash = `#/${path}`;
}
function heading(eyebrow, title, subtitle, ...actions) {
    return el('header', 'page-heading', el('div', '', el('p', 'eyebrow', eyebrow), el('h1', '', title), el('p', 'muted page-description', subtitle)), el('div', 'heading-actions', ...actions));
}
function panel(title, body, trailing) {
    return el('section', 'panel', el('div', 'panel-heading', el('h2', '', title), trailing), body);
}
function link(text, path, className = 'text-link') {
    const result = el('a', className, text);
    result.href = `#/${path}`;
    return result;
}
function writable(user) {
    return user.workspaces.find(workspace => workspace.id === getWorkspace())?.role !== 'viewer';
}
function admin(user) {
    return ['owner', 'admin'].includes(user.workspaces.find(workspace => workspace.id === getWorkspace())?.role ?? '');
}
export async function newWorkflow() {
    const projects = await api('/projects');
    const name = input('New workflow');
    name.maxLength = 100;
    const project = select(projects.items.map(value => ({ value: value.id, text: value.name })));
    const template = select(templates.map((value, index) => ({ value: String(index), text: value.name })));
    const note = el('p', 'callout', templates[0].description);
    template.addEventListener('change', () => {
        const item = templates[Number(template.value)];
        name.value = item.name;
        note.textContent = item.description;
    });
    const content = el('div', 'modal-body', field('Workflow name', name), field('Project', project), field('Starting point', template), note, el('p', 'muted small', 'Templates are editable. AI examples use a deterministic fixture; they do not contact a live provider.'));
    const submit = button('Create workflow', async () => {
        await busy(submit, async () => {
            const item = templates[Number(template.value)];
            const result = await post('/workflows', { name: name.value, project_id: project.value, description: item.description, definition: item.definition });
            dialog.close();
            navigate(`workflows/${result.id}`);
            revealSecret('Webhook signing key', result.webhook_secret, 'This key is shown once. Store it securely, or rotate it later from this workflow. Never commit it to a repository.');
        });
    }, 'button primary', 'plus');
    const dialog = modal('Create workflow', content, [submit]);
}
function revealSecret(title, value, description) {
    const code = el('pre', 'secret-value', value);
    const content = el('div', 'modal-body', el('p', 'muted', description), code);
    const dialog = modal(title, content, [button('Copy key', () => copy(value), 'button', 'copy'), button('I have saved it', () => dialog.close(), 'button primary')]);
}
export function runTable(items) {
    if (!items.length)
        return empty('No executions yet', 'Publish a workflow, then send its first event.');
    const table = el('table', 'data-table');
    table.append(el('thead', '', el('tr', '', ...['Execution', 'Workflow', 'Status', 'Source', 'Duration', 'Started'].map(value => el('th', '', value)))));
    const body = el('tbody');
    for (const run of items) {
        const elapsed = run.started_at && run.finished_at ? (run.finished_at - run.started_at) * 1000 : null;
        body.append(el('tr', '', el('td', '', link(run.id.slice(0, 8), `runs/${run.id}`, 'mono table-link')), el('td', '', el('strong', 'table-name', run.workflow_name || 'Workflow'), el('span', 'row-subtitle', `Version ${run.version ?? '—'}`)), el('td', '', badge(run.status)), el('td', '', el('span', 'subtle-tag', run.dry_run ? 'Dry run' : label(run.source))), el('td', 'mono muted', duration(elapsed)), el('td', 'muted nowrap', timestamp(run.created_at))));
    }
    table.append(body);
    return el('div', 'table-scroll', table);
}
function activityChart(data) {
    const chart = el('div', 'activity-chart');
    chart.setAttribute('role', 'img');
    chart.setAttribute('aria-label', data.map(day => `${new Date(day.date * 1000).toLocaleDateString('en', { timeZone: 'UTC' })}: ${day.total} executions`).join('. '));
    const maximum = Math.max(1, ...data.map(day => day.total));
    const columns = el('div', 'chart-columns');
    for (const day of data) {
        const total = el('div', 'chart-bar');
        total.style.height = `${Math.max(2, day.total / maximum * 130)}px`;
        if (day.total === 0)
            total.classList.add('zero');
        const success = el('div', 'chart-success');
        success.style.height = `${day.total ? day.succeeded / day.total * 100 : 0}%`;
        total.append(success);
        columns.append(el('div', 'chart-column', el('span', 'chart-value mono', day.total || ''), total, el('span', 'chart-label', new Date(day.date * 1000).toLocaleDateString('en', { weekday: 'short', timeZone: 'UTC' }))));
    }
    chart.append(columns, el('div', 'chart-legend', el('span', 'legend-item', el('i', 'legend-dot'), 'Succeeded'), el('span', 'legend-item', el('i', 'legend-dot muted-dot'), 'Other states'), el('span', 'chart-timezone', 'UTC')));
    return chart;
}
export async function overviewPage(user) {
    const data = await api('/overview');
    const create = button('New workflow', newWorkflow, 'button primary', 'plus');
    create.disabled = !writable(user);
    const page = el('div', 'page');
    page.append(heading('CONTROL PLANE', 'Execution overview', 'A clear view of the work moving through your system.', el('span', 'range-label', icon('clock'), 'Last 7 days'), create));
    const pending = Object.entries(data.counts).filter(([state]) => !['succeeded', 'failed', 'cancelled'].includes(state)).reduce((sum, [, count]) => sum + count, 0);
    const stat = (title, value, note, symbol, accent = false) => el('section', `stat-card ${accent ? 'accent' : ''}`, el('div', 'stat-label', title, icon(symbol)), el('strong', 'stat-value', value), el('span', 'stat-note', note));
    page.append(el('div', 'stats-grid', stat('Workflows', String(data.workflow_count), 'Across this workspace', 'workflow'), stat('Executions', String(data.total), `${data.dry_runs} dry runs included`, 'runs'), stat('Success rate', data.success_rate === null ? '—' : `${data.success_rate}%`, 'Succeeded ÷ (succeeded + failed)', 'check', true), stat('In progress', String(pending), 'Queued, running or waiting', 'clock')));
    const waiting = data.recent.filter(run => run.status === 'waiting');
    const attention = el('div', 'attention-body', el('div', 'attention-symbol', icon('pause')), el('h3', '', pending ? 'Some work is still in flight' : 'Nothing needs your attention'), el('p', 'muted small', 'Durable waits and approvals release workers. Open an execution to inspect its next action.'));
    for (const run of waiting.slice(0, 2))
        attention.append(link(run.workflow_name + ' →', `runs/${run.id}`, 'attention-link'));
    if (!waiting.length)
        attention.append(link('View executions →', 'runs', 'attention-link'));
    page.append(el('div', 'overview-middle', panel('Execution activity', activityChart(data.activity), el('span', 'panel-caption', 'Actual execution records')), panel('On your radar', attention)));
    page.append(panel('Recent executions', runTable(data.recent), link('View all executions', 'runs')));
    page.append(el('div', 'bottom-note', icon('info'), 'Metrics describe this installation only. Seeded examples are labeled Demo; fixture AI is not live inference.'));
    return page;
}
export async function workflowsPage(user) {
    const data = await api('/workflows?limit=100');
    const create = button('New workflow', newWorkflow, 'button primary', 'plus');
    create.disabled = !writable(user);
    const page = el('div', 'page', heading('AUTOMATION', 'Workflows', 'Edit safely. Publish an immutable version. Run it with a complete execution record.', create));
    const filter = input();
    filter.placeholder = 'Search workflows';
    filter.setAttribute('aria-label', 'Search workflows');
    const content = el('div', 'workflow-grid');
    const render = () => {
        content.replaceChildren();
        const matches = data.items.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(filter.value.toLowerCase()));
        for (const workflow of matches) {
            const card = el('article', 'workflow-card', el('div', 'workflow-card-top', el('div', 'workflow-symbol', icon('workflow')), badge(workflow.published_version ? 'published' : 'draft')), el('h2', '', link(workflow.name, `workflows/${workflow.id}`, 'card-title')), el('p', 'muted', workflow.description || 'No description yet.'), el('div', 'workflow-tags', el('span', 'subtle-tag', workflow.environment), el('span', 'subtle-tag', workflow.published_version ? `v${workflow.published_version}` : 'Unpublished')), el('div', 'workflow-card-footer', el('span', 'small muted', `Updated ${timestamp(workflow.updated_at)}`), link('Open →', `workflows/${workflow.id}`)));
            content.append(card);
        }
        if (!matches.length)
            content.append(empty('No matching workflows', data.total ? 'Try another search.' : 'Create a workflow to get started.'));
    };
    filter.addEventListener('input', render);
    render();
    page.append(el('div', 'toolbar', filter, el('span', 'muted small', `${data.total} workflows${data.total > 100 ? ' · first 100 shown' : ''}`)), content);
    return page;
}
function sampleInput(definition) {
    const properties = definition.input_schema.properties;
    const defaults = { company: 'Example Studio', message: 'We need help connecting an API to our app.', budget: 12000, amount: 1500, name: 'Example event' };
    return Object.fromEntries(Object.entries(properties ?? {}).map(([key, value]) => [key, defaults[key] ?? (value.type === 'number' || value.type === 'integer' ? 1 : value.type === 'boolean' ? true : value.type === 'array' ? [] : value.type === 'object' ? {} : 'Example')]));
}
async function startRun(workflow) {
    const payload = textArea(JSON.stringify(sampleInput(workflow.definition), null, 2), 9);
    const dry = input('', 'checkbox');
    dry.checked = workflow.definition.nodes.some(node => node.type === 'http');
    const content = el('div', 'modal-body', el('p', 'muted', `This execution uses published version ${workflow.published_version}. Unsaved changes are not included.`), field('JSON input', payload), el('label', 'check-field', dry, 'Dry run: suppress outbound requests and use AI fixtures'));
    const submit = button('Start execution', async () => {
        await busy(submit, async () => {
            const result = await post(`/workflows/${workflow.id}/runs`, { input: JSON.parse(payload.value), dry_run: dry.checked }, { 'Idempotency-Key': crypto.randomUUID() });
            dialog.close();
            navigate(`runs/${result.id}`);
            toast('Execution queued');
        });
    }, 'button primary', 'runs');
    const dialog = modal('Run workflow', content, [submit]);
}
export async function workflowPage(id, user) {
    let workflow = await api(`/workflows/${id}`);
    const name = input(workflow.name);
    const description = input(workflow.description);
    const concurrent = input(String(workflow.max_concurrency), 'number');
    concurrent.min = '1';
    concurrent.max = '16';
    const editor = textArea(JSON.stringify(workflow.definition, null, 2), 22);
    editor.setAttribute('aria-label', 'Workflow JSON definition');
    const revision = el('span', 'subtle-tag', `Draft ${workflow.draft_revision}`);
    const graphArea = el('div', '', graph(workflow.definition.nodes));
    const validate = button('Validate', async () => {
        const definition = JSON.parse(editor.value);
        await post('/definitions/validate', definition);
        graphArea.replaceChildren(graph(definition.nodes));
        toast('Definition is valid');
    }, 'button quiet', 'check');
    const saveChanges = async () => {
        const result = await api(`/workflows/${id}`, { method: 'PATCH', body: JSON.stringify({ definition: JSON.parse(editor.value), expected_revision: workflow.draft_revision, name: name.value, description: description.value, max_concurrency: Number(concurrent.value) }) });
        workflow = { ...workflow, ...result, definition: JSON.parse(editor.value) };
        revision.textContent = `Draft ${workflow.draft_revision}`;
        graphArea.replaceChildren(graph(workflow.definition.nodes));
    };
    const save = button('Save draft', async () => busy(save, async () => { await saveChanges(); toast('Draft saved'); }), 'button', 'save');
    const publish = button('Publish version', async () => busy(publish, async () => {
        await saveChanges();
        const result = await post(`/workflows/${id}/publish`, { expected_revision: workflow.draft_revision });
        toast(`Version ${result.number} published`);
        window.dispatchEvent(new Event('flowpilot:refresh'));
    }), 'button primary', 'arrow');
    const run = button('Run', () => startRun(workflow), 'button', 'runs');
    run.disabled = !workflow.published_version || !writable(user);
    save.disabled = publish.disabled = validate.disabled = !writable(user);
    const page = el('div', 'page', heading('WORKFLOW', workflow.name, workflow.description || 'Define how an event moves through your system.', run, save, publish));
    page.append(el('div', 'workflow-meta', badge(workflow.published_version ? 'published' : 'draft'), revision, el('span', 'subtle-tag', workflow.environment), el('code', 'muted small', id)));
    page.append(panel('Execution path', graphArea, el('span', 'panel-caption', 'Dependencies run in topological order')));
    const settings = el('div', 'form-row', field('Name', name), field('Description', description), field('Concurrent steps', concurrent));
    const download = button('Export JSON', () => {
        const url = URL.createObjectURL(new Blob([editor.value], { type: 'application/json' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'workflow.json';
        anchor.click();
        URL.revokeObjectURL(url);
    }, 'button quiet', 'code');
    page.append(panel('Definition', el('div', 'panel-content', settings, el('p', 'muted small', 'Edit the JSON contract. Validate before saving. Running executions keep their original published version.'), editor), el('div', 'row-actions', validate, download)));
    const versionRows = el('div', 'version-list');
    for (const version of workflow.versions) {
        const activate = button(version.number === workflow.published_version ? 'Active' : 'Activate', async () => {
            await post(`/workflows/${id}/activate`, { number: version.number });
            toast(`Version ${version.number} activated`);
            window.dispatchEvent(new Event('flowpilot:refresh'));
        }, 'button small-button');
        activate.disabled = version.number === workflow.published_version || !writable(user);
        versionRows.append(el('div', 'version-row', el('strong', '', `v${version.number}`), el('code', 'muted small', version.digest.slice(0, 14)), el('span', 'muted small', timestamp(version.created_at)), activate));
    }
    if (!workflow.versions.length)
        versionRows.append(empty('No published versions', 'Publishing creates an immutable snapshot.'));
    const rotate = button('Rotate signing key', async () => {
        if (!confirm('Rotate the webhook key? Existing senders will need the new key.'))
            return;
        const result = await post(`/workflows/${id}/rotate-webhook`);
        revealSecret('New webhook key', result.webhook_secret, 'Update authorized senders. The previous key no longer works.');
    }, 'button quiet', 'key');
    rotate.disabled = !admin(user);
    page.append(el('div', 'two-panels', panel('Published versions', versionRows), panel('Inbound webhook', el('div', 'panel-content', el('p', 'muted small', 'Sign the timestamp, event ID and raw request body with HMAC SHA-256. Repeated event IDs are deduplicated.'), el('code', 'endpoint', workflow.webhook_path), rotate))));
    return page;
}
export async function runsPage() {
    const params = new URLSearchParams(location.hash.split('?')[1]);
    const status = params.get('status') ?? '';
    const pageNumber = Math.max(0, Number(params.get('page')) || 0);
    const data = await api(`/runs?limit=20&offset=${pageNumber * 20}&status=${encodeURIComponent(status)}`);
    const filter = select(['', 'queued', 'running', 'waiting', 'retry_wait', 'succeeded', 'failed', 'cancelled'].map(value => ({ value, text: value ? label(value) : 'All statuses' })), status);
    filter.setAttribute('aria-label', 'Filter executions by status');
    filter.addEventListener('change', () => navigate(`runs?status=${filter.value}`));
    const previous = button('Previous', () => navigate(`runs?page=${pageNumber - 1}&status=${status}`));
    const next = button('Next', () => navigate(`runs?page=${pageNumber + 1}&status=${status}`));
    previous.disabled = pageNumber === 0;
    next.disabled = (pageNumber + 1) * 20 >= data.total;
    return el('div', 'page', heading('RUNTIME', 'Executions', 'Every step, attempt and result. Including the ones that did not go to plan.'), el('div', 'toolbar', filter, el('span', 'muted small', `${data.total} executions`)), panel('Execution history', runTable(data.items)), el('div', 'pagination', previous, el('span', 'small muted', `Page ${pageNumber + 1}`), next));
}
async function replay(run) {
    const dry = input('', 'checkbox');
    dry.checked = true;
    const acknowledged = input('', 'checkbox');
    const content = el('div', 'modal-body', el('p', 'callout', 'Replay creates a new execution of the original version. Real outbound actions can happen again, even if the original run succeeded.'), el('label', 'check-field', dry, 'Dry run: no external requests'), el('label', 'check-field', acknowledged, 'I understand that a live replay may repeat side effects'));
    const submit = button('Create replay', async () => busy(submit, async () => {
        const result = await post(`/runs/${run.id}/replay`, { dry_run: dry.checked, acknowledge_side_effects: acknowledged.checked });
        dialog.close();
        navigate(`runs/${result.id}`);
    }), 'button primary');
    const dialog = modal('Replay execution', content, [submit]);
}
export async function runPage(id, user) {
    const run = await api(`/runs/${id}`);
    const isClosed = ['succeeded', 'failed', 'cancelled'].includes(run.status);
    const cancel = button('Cancel execution', async () => {
        if (!confirm('Cancel this execution? An external request already in flight cannot be undone.'))
            return;
        await post(`/runs/${id}/cancel`);
        window.dispatchEvent(new Event('flowpilot:refresh'));
    }, 'button danger', 'close');
    cancel.disabled = isClosed || !writable(user);
    const replayButton = button('Replay', () => replay(run), 'button', 'runs');
    replayButton.disabled = !writable(user);
    const page = el('div', 'page', heading('EXECUTION RECORD', run.workflow_name, `Execution ${id.slice(0, 8)} from version ${run.version}`, cancel, replayButton));
    page.append(el('div', 'execution-meta', badge(run.status), el('span', 'subtle-tag', run.dry_run ? 'Dry run' : label(run.source)), el('span', 'muted small', timestamp(run.created_at)), link('Open workflow →', `workflows/${run.workflow_id}`)));
    if (run.error_code)
        page.append(el('div', 'callout error-callout', icon('info'), el('span', '', `Execution stopped: ${run.error_code}`)));
    const timeline = el('div', 'timeline');
    for (const [index, step] of run.steps.entries()) {
        const details = el('details', 'step-record');
        details.dataset.step = step.id;
        details.open = step.status === 'awaiting_approval' || step.status === 'failed';
        const title = el('summary', 'step-summary', el('span', `step-number ${step.status}`, step.status === 'succeeded' ? icon('check') : String(index + 1).padStart(2, '0')), el('div', 'step-title', el('strong', '', step.label), el('span', 'small muted', `${label(step.type)} · ${step.id}`)), badge(step.status), el('span', 'mono muted step-duration', duration(step.duration_ms)));
        const body = el('div', 'step-body');
        if (step.status === 'awaiting_approval') {
            const note = input();
            note.placeholder = 'Optional review note';
            note.setAttribute('aria-label', 'Approval note');
            const decide = async (approved) => {
                await post(`/runs/${id}/steps/${step.id}/approval`, { approved, note: note.value });
                toast(approved ? 'Approved. Execution will resume.' : 'Execution rejected.');
                window.dispatchEvent(new Event('flowpilot:refresh'));
            };
            const approve = button('Approve and continue', () => decide(true), 'button primary', 'check');
            const reject = button('Reject', () => decide(false), 'button danger');
            approve.disabled = reject.disabled = !writable(user);
            body.append(el('div', 'approval-box', el('h3', '', 'Human review required'), el('p', 'muted', step.approval_message ?? ''), note, el('div', 'row-actions', approve, reject)));
        }
        if (step.error_code)
            body.append(el('p', 'error-text', step.error_code));
        if (step.ready_at && ['waiting', 'retry_wait', 'awaiting_approval'].includes(step.status))
            body.append(el('p', 'small muted', `${step.status === 'awaiting_approval' ? 'Approval deadline' : 'Next eligible time'}: ${timestamp(step.ready_at)}`));
        body.append(el('h4', '', 'Output'), jsonView(step.output));
        if (Object.keys(step.usage).length)
            body.append(el('h4', '', 'Provider usage'), jsonView(step.usage));
        if (step.attempts.length) {
            body.append(el('h4', '', 'Attempts'));
            for (const attempt of step.attempts)
                body.append(el('div', 'attempt-row', el('span', 'mono', `#${attempt.number}`), badge(attempt.status), el('span', 'small muted', timestamp(attempt.started_at)), el('span', 'small mono', duration(attempt.duration_ms)), el('code', 'small error-text', attempt.error_code ?? '')));
        }
        details.append(title, body);
        timeline.append(details);
    }
    page.append(panel('Step timeline', timeline, el('span', 'panel-caption', `${run.steps.length} steps`)));
    const inputPanel = panel('Execution input', el('div', 'panel-content', jsonView(run.input)));
    const info = el('div', 'panel-content metadata-grid', el('span', 'muted', 'Run ID'), el('code', '', run.id), el('span', 'muted', 'Correlation ID'), el('code', '', run.trace_id), el('span', 'muted', 'Started'), el('span', '', timestamp(run.started_at)), el('span', 'muted', 'Finished'), el('span', '', timestamp(run.finished_at)));
    if (run.parent_id)
        info.append(el('span', 'muted', 'Replay of'), link(run.parent_id.slice(0, 8), `runs/${run.parent_id}`));
    page.append(el('div', 'two-panels', inputPanel, panel('Metadata', info)));
    return page;
}
async function credentialDialog() {
    const projects = await api('/projects');
    const name = input();
    const project = select(projects.items.map(item => ({ value: item.id, text: item.name })));
    const kind = select(['http', 'openai', 'anthropic', 'gemini'].map(value => ({ value, text: label(value) })));
    const host = input();
    host.placeholder = 'api.example.com';
    const value = input('', 'password');
    value.autocomplete = 'new-password';
    const content = el('div', 'modal-body', field('Name', name), field('Project', project), field('Provider', kind), field('Allowed host', host, 'Required for HTTP credentials. The server must also allow this destination.'), field('Secret value', value), el('p', 'small muted', 'The value is encrypted before storage and is never returned by the API.'));
    const submit = button('Save credential', async () => busy(submit, async () => {
        await post('/credentials', { name: name.value, project_id: project.value, kind: kind.value, allowed_host: host.value, value: value.value });
        value.value = '';
        dialog.close();
        toast('Credential saved');
        window.dispatchEvent(new Event('flowpilot:refresh'));
    }), 'button primary', 'key');
    const dialog = modal('Add credential', content, [submit]);
}
export async function credentialsPage(user) {
    const data = await api('/credentials');
    const create = button('Add credential', credentialDialog, 'button primary', 'plus');
    create.disabled = !admin(user);
    const page = el('div', 'page', heading('INTEGRATIONS', 'Credential vault', 'Encrypted, versioned secrets. Workflows reference credentials, never their values.', create));
    page.append(el('div', 'callout', icon('key'), 'New runs pin credential versions. Rotation does not rewrite running work. Revocation blocks future step access.'));
    const cards = el('div', 'workflow-grid');
    for (const credential of data.items) {
        const rotate = button('Rotate', async () => {
            const value = input('', 'password');
            value.autocomplete = 'new-password';
            const submit = button('Save new version', async () => busy(submit, async () => {
                await post(`/credentials/${credential.id}/rotate`, { value: value.value });
                value.value = '';
                dialog.close();
                window.dispatchEvent(new Event('flowpilot:refresh'));
            }), 'button primary');
            const dialog = modal('Rotate credential', el('div', 'modal-body', field('New secret', value), el('p', 'muted small', 'Existing runs retain the pinned version. Revoke the credential to block further access.')), [submit]);
        }, 'button small-button');
        const revoke = button('Revoke', async () => {
            if (!confirm('Revoke this credential? Pending steps using it will fail.'))
                return;
            await post(`/credentials/${credential.id}/revoke`);
            window.dispatchEvent(new Event('flowpilot:refresh'));
        }, 'button quiet small-button');
        rotate.disabled = revoke.disabled = credential.revoked || !admin(user);
        cards.append(el('article', 'workflow-card', el('div', 'workflow-card-top', el('div', 'workflow-symbol', icon('key')), badge(credential.revoked ? 'revoked' : 'active')), el('h2', '', credential.name), el('p', 'muted', `${label(credential.kind)} · Version ${credential.version}`), el('code', 'small muted break-word', credential.id), el('p', 'small muted', credential.allowed_host || 'Fixed provider endpoint'), el('div', 'row-actions', rotate, revoke)));
    }
    page.append(data.items.length ? cards : panel('Stored credentials', empty('No secrets configured', 'Fixture workflows work without keys. Add a credential only when enabling a real integration.')));
    return page;
}
export async function workspacePage(user) {
    const data = await api('/workspace');
    const projects = await api('/projects');
    const page = el('div', 'page', heading('SETTINGS', 'Workspace', 'Members, projects and the audit trail for this installation.'));
    const members = el('div', 'member-list');
    for (const member of data.members)
        members.append(el('div', 'member-row', el('div', 'avatar', initials(member.name)), el('div', 'member-info', el('strong', '', member.name), el('span', 'muted small', member.email)), el('span', 'subtle-tag', label(member.role))));
    const addMember = button('Add member', () => {
        const email = input('', 'email');
        const role = select(['developer', 'viewer', 'admin'].map(value => ({ value, text: label(value) })));
        const submit = button('Save membership', async () => {
            await post('/members', { email: email.value, role: role.value });
            dialog.close();
            window.dispatchEvent(new Event('flowpilot:refresh'));
        }, 'button primary');
        const dialog = modal('Add an existing user', el('div', 'modal-body', field('Email', email), field('Role', role), el('p', 'muted small', 'An operator must first create the account with flowpilot create-user. No invitation email is sent.')), [submit]);
    }, 'button small-button', 'plus');
    addMember.disabled = !admin(user);
    page.append(panel('Members', members, addMember));
    const projectList = el('div', 'panel-content');
    for (const project of projects.items)
        projectList.append(el('div', 'version-row', el('strong', '', project.name), el('code', 'small muted', project.id)));
    const addProject = button('Add project', () => {
        const name = input();
        const submit = button('Create project', async () => { await post('/projects', { name: name.value }); dialog.close(); window.dispatchEvent(new Event('flowpilot:refresh')); }, 'button primary');
        const dialog = modal('Create project', el('div', 'modal-body', field('Name', name)), [submit]);
    }, 'button small-button', 'plus');
    addProject.disabled = !admin(user);
    const environment = el('div', 'panel-content metadata-grid', el('span', 'muted', 'Environment'), el('span', '', label(data.environment)), el('span', 'muted', 'Database'), el('span', '', data.database), el('span', 'muted', 'Active workers'), el('span', '', String(data.workers.length)), el('span', 'muted', 'Retention policy'), el('span', '', `${data.retention_days} days · requires scheduled purge`), el('span', 'muted', 'Outbound hosts'), el('code', '', data.egress_hosts.join(', ') || 'None allowed'));
    page.append(el('div', 'two-panels', panel('Projects', projectList, addProject), panel('Runtime configuration', environment)));
    const events = el('div', 'audit-list');
    for (const event of data.events)
        events.append(el('div', 'audit-row', el('div', 'audit-marker'), el('strong', 'mono small', event.action), el('code', 'muted small', event.resource_id.slice(0, 8)), el('time', 'muted small', timestamp(event.created_at))));
    page.append(panel('Recent audit events', data.events.length ? events : empty('No changes recorded', 'Configuration changes and operator actions appear here.'), el('span', 'panel-caption', 'Latest 50')));
    return page;
}
//# sourceMappingURL=pages.js.map