export function timestamp(value: number | null): string {
  return value === null ? 'Not yet' : new Date(value * 1000).toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

export function duration(milliseconds: number | null): string {
  if (milliseconds === null) return '—';
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(2)} s`;
  return `${Math.floor(milliseconds / 60000)}m ${Math.round(milliseconds % 60000 / 1000)}s`;
}

export function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/^./, character => character.toUpperCase());
}

export function initials(name: string): string {
  return name.split(' ').filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase();
}

export function nodesByDepth(nodes: { id: string; depends_on?: string[] }[]): Map<string, number> {
  const depth = new Map<string, number>();
  const pending = [...nodes];
  while (pending.length) {
    const index = pending.findIndex(node => (node.depends_on ?? []).every(parent => depth.has(parent)));
    if (index < 0) throw new Error('Cannot draw a cyclic workflow');
    const node = pending.splice(index, 1)[0]!;
    depth.set(node.id, 1 + Math.max(-1, ...(node.depends_on ?? []).map(parent => depth.get(parent)!)));
  }
  return depth;
}
