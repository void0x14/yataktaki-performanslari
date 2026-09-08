type Row = Record<string, any>;

export function evidenceImageRef(event: Row): string {
  const frame = String(event?.frame_ref || '');
  if (frame) return frame;
  const refs = Array.isArray(event?.evidence_refs) ? event.evidence_refs : [];
  return refs.map(String).find(ref => /\.(?:png|jpe?g|webp)$/i.test(ref)) || '';
}

export function checkedResponse(value: unknown): Row {
  if (!value || typeof value !== 'object' || !('ok' in value)) {
    throw new Error('Geçersiz agentd yanıtı');
  }
  const response = value as Row;
  if (response.ok !== true) {
    throw new Error([response.error, response.detail].filter(Boolean).join(' · ') || 'Komut reddedildi');
  }
  return response;
}

export function eventCursor(events: Row[]): number {
  return events.reduce((last, event) => Math.max(last, Number(event.seq) || 0), 0);
}

export function mergeEvents(previous: Row[], incoming: Row[], agentId: string): Row[] {
  const events = new Map<string, Row>();
  for (const event of [...previous, ...incoming]) {
    if (!event || event.agent_id !== agentId) continue;
    const key = String(event.event_id || event.seq || '');
    if (key) events.set(key, event);
  }
  return [...events.values()].sort((a, b) => Number(a.seq) - Number(b.seq)).slice(-250);
}
