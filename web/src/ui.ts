import { label, nodesByDepth } from './format.js';
import type { WorkflowNode } from './types.js';

type Child = Node | string | number | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', ...children: Child[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const paths: Record<string, string> = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  workflow: '<rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="15" y="15" width="6" height="6" rx="1.5"/><path d="M9 6h6a3 3 0 0 1 3 3v6M6 9v9h9"/>',
  runs: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
  key: '<circle cx="8" cy="9" r="5"/><path d="m12 12 9 9m-3-3 3-3m-6 3 3-3"/>',
  team: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m3 10v-3a5 5 0 0 0-2-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  code: '<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
  save: '<path d="M4 3h13l4 4v14H3V3zm3 0v6h10V3M7 21v-8h10v8"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  logout: '<path d="M9 3H3v18h6m5-4 5-5-5-5m-7 5h12"/>',
  network: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="m11 7-5 10m7-10 5 10M7 19h10"/>',
  ai: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  globe: '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
};

export function icon(name: string): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '18');
  svg.setAttribute('height', '18');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.65');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = paths[name] ?? paths.code!;
  return svg;
}

export function button(text: string, action: () => void | Promise<void>, className = 'button', symbol?: string): HTMLButtonElement {
  const result = el('button', className, symbol ? icon(symbol) : null, text);
  result.type = 'button';
  result.addEventListener('click', () => {
    Promise.resolve().then(action).catch(showError);
  });
  return result;
}

export function badge(status: string): HTMLElement {
  return el('span', `badge ${status}`, el('span', 'status-dot'), label(status));
}

export function toast(message: string, error = false): void {
  const item = el('div', `toast ${error ? 'error' : ''}`, icon(error ? 'info' : 'check'), message);
  document.querySelector('#toasts')?.append(item);
  setTimeout(() => item.remove(), error ? 8000 : 4500);
}

export function showError(error: unknown): void {
  toast(error instanceof Error ? error.message : 'The request could not be completed', true);
}

export function field(title: string, input: HTMLElement, hint?: string): HTMLElement {
  const id = input.id || `field-${crypto.randomUUID()}`;
  input.id = id;
  const caption = el('label', 'field-label', title);
  caption.htmlFor = id;
  return el('div', 'field', caption, input, hint ? el('p', 'field-hint', hint) : null);
}

export function input(value = '', type = 'text'): HTMLInputElement {
  const element = el('input', 'input');
  element.type = type;
  element.value = value;
  return element;
}

export function select(options: { value: string; text: string }[], selected?: string): HTMLSelectElement {
  const element = el('select', 'input');
  for (const item of options) {
    const option = el('option', '', item.text);
    option.value = item.value;
    option.selected = item.value === selected;
    element.append(option);
  }
  return element;
}

export function textArea(value: string, rows = 16): HTMLTextAreaElement {
  const area = el('textarea', 'input code-editor');
  area.rows = rows;
  area.spellcheck = false;
  area.value = value;
  return area;
}

export function modal(title: string, content: HTMLElement, actions: HTMLElement[] = []): { close: () => void; node: HTMLDialogElement } {
  const dialog = el('dialog', 'modal');
  const close = () => { dialog.close(); dialog.remove(); };
  const closeButton = button('', close, 'icon-button', 'close');
  closeButton.setAttribute('aria-label', 'Close dialog');
  dialog.append(el('div', 'modal-heading', el('h2', '', title), closeButton), content, el('div', 'modal-actions', button('Cancel', close, 'button quiet'), ...actions));
  dialog.addEventListener('cancel', close);
  document.querySelector('#dialogs')?.append(dialog);
  dialog.showModal();
  return { close, node: dialog };
}

export async function busy(buttonElement: HTMLButtonElement, action: () => Promise<void>): Promise<void> {
  buttonElement.disabled = true;
  buttonElement.setAttribute('aria-busy', 'true');
  try { await action(); } finally {
    buttonElement.disabled = false;
    buttonElement.removeAttribute('aria-busy');
  }
}

export function copy(value: string): void {
  navigator.clipboard.writeText(value).then(() => toast('Copied to clipboard')).catch(showError);
}

export function empty(title: string, detail: string): HTMLElement {
  return el('div', 'empty', el('div', 'empty-icon', icon('workflow')), el('h3', '', title), el('p', '', detail));
}

export function jsonView(value: unknown): HTMLElement {
  return el('pre', 'json-view', JSON.stringify(value, null, 2) ?? 'No output');
}

export function graph(nodes: WorkflowNode[]): HTMLElement {
  const container = el('div', 'graph-wrap');
  const depth = nodesByDepth(nodes);
  const slots = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const column = depth.get(node.id)!;
    const row = slots.get(column) ?? 0;
    slots.set(column, row + 1);
    positions.set(node.id, { x: 24 + column * 214, y: 24 + row * 110 });
  }
  const columns = Math.max(...depth.values(), 0) + 1;
  const rows = Math.max(...slots.values(), 1);
  const canvas = el('div', 'graph-canvas');
  canvas.style.width = `${columns * 214 + 24}px`;
  canvas.style.height = `${rows * 110 + 16}px`;
  const lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  lines.classList.add('graph-lines');
  lines.setAttribute('width', String(columns * 214 + 24));
  lines.setAttribute('height', String(rows * 110 + 16));
  lines.setAttribute('aria-hidden', 'true');
  for (const node of nodes) {
    const position = positions.get(node.id)!;
    for (const parent of node.depends_on ?? []) {
      const source = positions.get(parent)!;
      const path = document.createElementNS(lines.namespaceURI, 'path');
      path.setAttribute('d', `M${source.x + 174},${source.y + 35} C${source.x + 197},${source.y + 35} ${position.x - 23},${position.y + 35} ${position.x},${position.y + 35}`);
      lines.append(path);
    }
    const symbols: Record<string, string> = { set: 'code', condition: 'filter', ai: 'ai', approval: 'team', delay: 'clock', http: 'globe' };
    const nodeBox = el('div', `graph-node type-${node.type}`, el('div', 'node-top', icon(symbols[node.type]!), el('span', '', label(node.type))), el('strong', '', node.label || node.id));
    nodeBox.style.left = `${position.x}px`;
    nodeBox.style.top = `${position.y}px`;
    canvas.append(nodeBox);
  }
  canvas.prepend(lines);
  container.append(canvas);
  return container;
}
