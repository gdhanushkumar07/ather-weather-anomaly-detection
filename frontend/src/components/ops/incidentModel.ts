/**
 * Operational view of an incident — derived ONLY from the persisted incident
 * record (status, timeline, context captured at detection, work orders).
 * Nothing here decides whether something is anomalous; it only arranges what
 * the backend recorded.
 */

export const LAYER_NAME: Record<string, string> = {
  L1: 'Physics', L2: 'Temporal', L3: 'Multivariate', L4: 'Spatial', L5: 'Sensor health',
};

export const LAYER_STATE: Record<string, string> = {
  PASS: 'Nominal', WARNING: 'Warning', ANOMALY: 'Anomalous', VETO: 'Anomalous (veto)',
  INSUFFICIENT_DATA: 'Not evaluated', NOT_APPLICABLE: 'Not applicable', UNAVAILABLE: 'Unavailable',
};

export const WO_LABEL: Record<string, string> = {
  CREATED: 'Created', ASSIGNED: 'Assigned', IN_PROGRESS: 'In progress', COMPLETED: 'Completed',
};
export const WO_NEXT: Record<string, string | undefined> = {
  CREATED: 'ASSIGNED', ASSIGNED: 'IN_PROGRESS', IN_PROGRESS: 'COMPLETED',
};

export const isClosed = (i: any) => i?.status === 'RESOLVED' || i?.status === 'DISMISSED';
export const openWorkOrder = (wos: any[] | undefined) => (wos || []).find((w) => w.status !== 'COMPLETED');

/** One operational status for the queue: the lifecycle state, or "Action
 *  required" while a work order raised from the incident is still open. */
export function opsStatus(inc: any): { label: string; tone: 'new' | 'active' | 'action' | 'closed' } {
  if (inc.status === 'RESOLVED') return { label: 'Resolved', tone: 'closed' };
  if (inc.status === 'DISMISSED') return { label: 'Dismissed', tone: 'closed' };
  const wo = inc.work_order || openWorkOrder(inc.work_orders);
  if (wo && wo.status !== 'COMPLETED') return { label: `Action required · ${WO_LABEL[wo.status] || wo.status}`, tone: 'action' };
  if (wo && wo.status === 'COMPLETED') return { label: 'Action completed', tone: 'active' };
  const L: Record<string, string> = { NEW: 'New', ACKNOWLEDGED: 'Acknowledged', INVESTIGATING: 'Investigating', ESCALATED: 'Escalated' };
  return { label: L[inc.status] || inc.status, tone: inc.status === 'NEW' ? 'new' : 'active' };
}

export interface Step { key: string; label: string; at: string | null; done: boolean; note?: string }

const firstEvent = (inc: any, ...events: string[]) =>
  (inc.timeline || []).find((t: any) => events.includes(t.event))?.at || null;

/** Lifecycle stepper: each step is done only if the record shows it happened. */
export function lifecycleSteps(inc: any): Step[] {
  const wos: any[] = inc.work_orders || [];
  const lastWo = wos[wos.length - 1];
  const closedAt = firstEvent(inc, 'RESOLVED', 'DISMISSED');
  return [
    { key: 'detected', label: 'Anomaly detected', at: inc.context?.first_observation_at || inc.detected_at, done: true },
    { key: 'created', label: 'Incident created', at: inc.created_at, done: true },
    { key: 'ack', label: 'Acknowledged', at: firstEvent(inc, 'ACKNOWLEDGED'), done: !!firstEvent(inc, 'ACKNOWLEDGED') },
    { key: 'inv', label: 'Investigating', at: firstEvent(inc, 'INVESTIGATING'), done: !!firstEvent(inc, 'INVESTIGATING') },
    {
      key: 'action', label: lastWo ? (lastWo.status === 'COMPLETED' ? 'Action completed' : 'Action required') : 'Action',
      at: lastWo ? (lastWo.completed_at || lastWo.created_at) : null, done: !!lastWo && lastWo.status === 'COMPLETED',
      note: lastWo ? `${lastWo.work_order_id} · ${WO_LABEL[lastWo.status]}` : undefined,
    },
    {
      key: 'closed', label: inc.status === 'DISMISSED' ? 'Dismissed' : 'Resolved', at: closedAt, done: isClosed(inc),
    },
  ];
}

/** The real timeline: backend lifecycle narrative, in time order. */
export function timeline(inc: any): { stage: string; at: string; detail?: string; actor?: string }[] {
  return (inc.lifecycle || [])
    .filter((s: any) => s.at)
    .map((s: any) => (!inc.context && s.stage === 'OBSERVATION' ? { ...s, stage: 'LATEST_OBSERVATION' } : s))
    .sort((a: any, b: any) => Date.parse(a.at) - Date.parse(b.at));
}

export const human = (s: unknown) => String(s ?? '').replace(/_/g, ' ').toLowerCase();

export function layerRows(inc: any): { code: string; name: string; state: string; reason: string; score: number | null; triggered: boolean }[] {
  const lr = inc.context?.layer_results || {};
  return Object.keys(LAYER_NAME).filter((c) => lr[c]).map((c) => ({
    code: c, name: LAYER_NAME[c], state: LAYER_STATE[String(lr[c].status).toUpperCase()] || human(lr[c].status),
    reason: lr[c].reason || '—', score: typeof lr[c].score === 'number' ? lr[c].score : null, triggered: !!lr[c].triggered,
  }));
}

export const PRIORITY_FROM_SEVERITY: Record<string, string> = { CRITICAL: 'HIGH', WARNING: 'MEDIUM', INFO: 'LOW' };
