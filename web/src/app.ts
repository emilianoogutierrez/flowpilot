import { api, ApiError, getWorkspace, post, setWorkspace } from './api.js';
import { initials } from './format.js';
import { credentialsPage, navigation, overviewPage, runPage, runsPage, workflowPage, workflowsPage, workspacePage } from './pages.js';
import type { User } from './types.js';
import { busy, button, el, field, icon, input, select, showError } from './ui.js';

const root = document.querySelector<HTMLDivElement>('#app')!;
let user: User | null = null;
let generation = 0;
let currentPage: HTMLElement | null = null;
let currentBreadcrumb: HTMLElement | null = null;
let mountedHash = '';

function loginScreen(): void {
  generation++;
  const email = input('', 'email'); email.autocomplete = 'username'; email.required = true;
  const password = input('', 'password'); password.autocomplete = 'current-password'; password.required = true;
  const errorMessage = el('p', 'form-error'); errorMessage.setAttribute('role', 'alert');
  const submit = el('button', 'button primary login-submit', 'Sign in', icon('arrow')); submit.type = 'submit';
  const form = el('form', 'login-form', el('div', 'brand login-brand', el('span', 'brand-mark', 'F'), 'flowpilot'), el('p', 'eyebrow', 'WORKFLOW EXECUTION CONSOLE'), el('h1', '', 'Welcome back.'), el('p', 'muted', 'Sign in to inspect, run and improve your workflows.'), field('Email address', email), field('Password', password), errorMessage, submit, el('p', 'login-footnote', 'Local setup? Your generated demo credentials are in .env.'));
  form.addEventListener('submit', event => {
    event.preventDefault();
    errorMessage.textContent = '';
    busy(submit, async () => {
      try {
        user = await post<User>('/auth/login', { email: email.value, password: password.value });
        password.value = '';
        selectWorkspace();
        mountShell();
        await renderRoute();
      } catch (error) {
        errorMessage.textContent = error instanceof Error ? error.message : 'Unable to sign in';
      }
    }).catch(showError);
  });
  const illustration = el('div', 'login-aside', el('div', 'login-orbit', icon('workflow')), el('div', '', el('span', 'eyebrow', 'CLARITY AT EVERY STEP'), el('h2', '', 'Make the work visible.'), el('p', '', 'Versioned workflows. Durable execution. A record of what happened, not a guess about what should have happened.')));
  root.replaceChildren(el('main', 'login-layout', el('div', 'login-panel', form), illustration));
  document.title = 'Sign in · FlowPilot';
}

function selectWorkspace(): void {
  if (!user?.workspaces.length) throw new Error('This account has no workspace. Ask the operator to add a membership.');
  if (!user.workspaces.some(workspace => workspace.id === getWorkspace())) setWorkspace(user.workspaces[0]!.id);
}

function mountShell(): void {
  if (!user) return;
  const workspace = user.workspaces.find(item => item.id === getWorkspace())!;
  const choice = select(user.workspaces.map(item => ({ value: item.id, text: item.name })), workspace.id);
  choice.classList.add('workspace-select'); choice.setAttribute('aria-label', 'Workspace');
  choice.addEventListener('change', () => { setWorkspace(choice.value); mountShell(); void renderRoute(); });
  const nav = el('nav', 'navigation'); nav.setAttribute('aria-label', 'Main navigation');
  for (const item of navigation) {
    const anchor = el('a', 'nav-link', icon(item.icon), item.label);
    anchor.href = `#/${item.path}`; anchor.dataset.route = item.path;
    nav.append(anchor);
  }
  const signout = button('', async () => {
    await post('/auth/logout'); user = null; loginScreen();
  }, 'icon-button', 'logout'); signout.setAttribute('aria-label', 'Sign out');
  const sidebar = el('aside', 'sidebar', el('a', 'brand', el('span', 'brand-mark', 'F'), 'flowpilot'), el('div', 'workspace-selector', el('span', 'sidebar-label', 'WORKSPACE'), choice), el('span', 'sidebar-label nav-label', 'BUILD & OPERATE'), nav, el('div', 'sidebar-bottom', el('div', 'sidebar-note', el('span', 'status-dot'), 'Self-hosted console', el('span', 'mono small muted', 'v0.1.0')), el('div', 'user-block', el('div', 'avatar', initials(user.name)), el('div', 'user-info', el('strong', '', user.name), el('span', 'muted small', workspace.role)), signout)));
  const brand = sidebar.querySelector<HTMLAnchorElement>('.brand')!; brand.href = '#/overview';
  currentBreadcrumb = el('span', '', 'Overview');
  const reference = el('a', 'api-link', icon('code'), 'API schema'); reference.href = '/api/openapi.json'; reference.target = '_blank'; reference.rel = 'noopener';
  const topbar = el('div', 'topbar', el('div', 'breadcrumbs', el('span', 'muted', workspace.name), icon('chevron'), currentBreadcrumb), el('div', 'topbar-right', el('span', 'connection-state', el('span', 'status-dot'), 'Connected'), reference));
  currentPage = el('main', 'main-content'); currentPage.id = 'main';
  root.replaceChildren(el('div', 'app-shell', sidebar, el('div', 'workspace-shell', topbar, currentPage)));
}

async function renderRoute(quiet = false): Promise<void> {
  if (!user || !currentPage) return;
  const ticket = ++generation;
  const route = location.hash.replace(/^#\/?/, '') || 'overview';
  const path = route.split('?')[0]!.split('/');
  const section = path[0]!;
  const pageElement = currentPage;
  const openSteps = new Set([...pageElement.querySelectorAll<HTMLDetailsElement>('details[open]')].map(item => item.dataset.step));
  for (const anchor of document.querySelectorAll<HTMLAnchorElement>('.nav-link')) {
    const active = anchor.dataset.route === section;
    anchor.classList.toggle('active', active);
    if (active) anchor.setAttribute('aria-current', 'page'); else anchor.removeAttribute('aria-current');
  }
  if (currentBreadcrumb) currentBreadcrumb.textContent = navigation.find(item => item.path === section)?.label ?? 'Overview';
  if (!quiet) pageElement.replaceChildren(el('div', 'loading', el('span', 'spinner'), 'Loading workspace…'));
  document.title = `${navigation.find(item => item.path === section)?.label ?? 'Overview'} · FlowPilot`;
  try {
    let content: HTMLElement;
    if (section === 'workflows' && path[1]) content = await workflowPage(path[1], user);
    else if (section === 'workflows') content = await workflowsPage(user);
    else if (section === 'runs' && path[1]) content = await runPage(path[1], user);
    else if (section === 'runs') content = await runsPage();
    else if (section === 'credentials') content = await credentialsPage(user);
    else if (section === 'workspace') content = await workspacePage(user);
    else content = await overviewPage(user);
    if (ticket !== generation) return;
    if (quiet && mountedHash === route) {
      for (const details of content.querySelectorAll<HTMLDetailsElement>('details')) if (openSteps.has(details.dataset.step)) details.open = true;
    }
    pageElement.replaceChildren(content);
    mountedHash = route;
  } catch (error) {
    if (ticket !== generation) return;
    if (error instanceof ApiError && error.status === 401) { user = null; loginScreen(); return; }
    if (quiet) { showError(error); return; }
    pageElement.replaceChildren(el('div', 'page', el('div', 'error-state', icon('info'), el('h1', '', 'Could not load this view'), el('p', 'muted', error instanceof Error ? error.message : 'Unknown error'), button('Try again', () => renderRoute(), 'button primary'))));
  }
}

window.addEventListener('hashchange', () => void renderRoute());
window.addEventListener('flowpilot:refresh', () => void renderRoute(true));
setInterval(() => {
  const route = location.hash;
  const formFocused = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName ?? '');
  if (user && !document.hidden && !formFocused && !document.querySelector('dialog[open]') && (route.includes('/runs') || route.includes('/overview') || !route)) void renderRoute(true);
}, 5000);

async function start(): Promise<void> {
  try { user = await api<User>('/auth/me'); selectWorkspace(); mountShell(); await renderRoute(); }
  catch { loginScreen(); }
}

void start();
