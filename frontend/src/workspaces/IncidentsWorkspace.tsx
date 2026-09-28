import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ClipboardList, FileText, MapPinned, Search as InvestigateIcon, Siren, UserCheck, Wrench, XCircle } from 'lucide-react';
import {
  acknowledgeIncident, advanceWorkOrder, createWorkOrder, dismissIncident, fetchIncidentDetail, fetchIncidents, investigateIncident, resolveIncident,
} from '../services/api';
import { formatAge, useLiveEvents } from '../services/live';
import { Card, Empty, SourceBadge, fmtDateTime } from '../components/live/LiveBits';
import { EscalationPreviewModal } from '../components/EscalationPreviewModal';
import { ResolveIncidentModal } from '../components/ResolveIncidentModal';
import { DismissIncidentModal } from '../components/DismissIncidentModal';
import { IncidentReport } from '../components/ops/IncidentReport';
import {
  PRIORITY_FROM_SEVERITY, WO_LABEL, WO_NEXT, human, isClosed, layerRows, lifecycleSteps, openWorkOrder, opsStatus, timeline,
} from '../components/ops/incidentModel';

interface Props {
  openIncidentId: string | null;
  onOpenIncident: (id: string | null) => void;
  onInvestigate: (id: string) => void;
  onOpenStation: (id: string) => void;
  onShowOnMap: (id: string) => void;
}

type View = 'open' | 'action' | 'closed' | 'all';
const SEV: Record<string, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 };
const NEXT: Record<string, string[]> = {
  NEW: ['ACKNOWLEDGED', 'DISMISSED'], ACKNOWLEDGED: ['INVESTIGATING', 'DISMISSED'],
  INVESTIGATING: ['ESCALATED', 'RESOLVED', 'DISMISSED'], ESCALATED: ['RESOLVED', 'DISMISSED'],
};
const TONE: Record<string, string> = { new: 'lv-status-suspect', active: 'lv-status-unknown', action: 'lv-status-anomaly', closed: 'lv-status-nominal' };

/**
 * INCIDENTS — the operational queue. Every row is an incident the backend
 * opened from fused evidence; this page moves it through its lifecycle
 * (acknowledge → investigate → action/work order → resolve) and produces
 * the report. The technical deep dive lives in Investigations.
 */
export const IncidentsWorkspace: React.FC<Props> = ({ openIncidentId, onOpenIncident, onInvestigate, onOpenStation, onShowOnMap }) => {
  const [all, setAll] = useState<any[] | null>(null);
  const [view, setView] = useState<View>('open');
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const load = () => fetchIncidents(null).then((r) => setAll(r.incidents || [])).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  useLiveEvents(['INCIDENT_CREATED', 'INCIDENT_UPDATED'], () => {
    if (Date.now() - last.current > 2000) { last.current = Date.now(); load(); }
  });

  const counts = useMemo(() => {
    const a = all || [];
    return {
      open: a.filter((i) => !isClosed(i)).length,
      action: a.filter((i) => opsStatus(i).tone === 'action').length,
      closed: a.filter(isClosed).length,
      all: a.length,
      critical: a.filter((i) => !isClosed(i) && i.severity === 'CRITICAL').length,
    };
  }, [all]);

  const list = useMemo(() => (all || [])
    .filter((i) => view === 'all' ? true : view === 'closed' ? isClosed(i) : view === 'action' ? opsStatus(i).tone === 'action' : !isClosed(i))
    .sort((a, b) => Number(isClosed(a)) - Number(isClosed(b)) || (SEV[a.severity] ?? 9) - (SEV[b.severity] ?? 9)
      || Date.parse(b.updated_at) - Date.parse(a.updated_at)), [all, view]);

  useEffect(() => {
    if (!openIncidentId && list.length) onOpenIncident(list[0].incident_id);
  }, [openIncidentId, list, onOpenIncident]);

  return (
    <div className="lv-page">
      <div className="lv-page-head">
        <div>
          <div className="a-eyebrow">Incidents</div>
          <h1 className="a-h1">{counts.open} open incident{counts.open === 1 ? '' : 's'}{counts.critical ? ` · ${counts.critical} critical` : ''}{counts.action ? ` · ${counts.action} awaiting action` : ''}</h1>
          <p className="a-lead">Opened automatically when fused evidence confirms a sensor problem. Monitor → detect → explain → respond → resolve.</p>
        </div>
      </div>
      {error && <div className="lv-callout danger">{error}</div>}

      <Card title="Incident queue" icon={<ClipboardList size={14} />}
        right={<div className="lv-tabs">{([['open', 'Open'], ['action', 'Action required'], ['closed', 'Closed'], ['all', 'All']] as [View, string][]).map(([k, l]) => (
          <button key={k} className={`lv-tab ${view === k ? 'active' : ''}`} onClick={() => setView(k)}>{l} <span className="lv-mono" style={{ fontSize: '0.64rem', color: 'var(--a-ink-3)' }}>{counts[k]}</span></button>
        ))}</div>}>
        {all === null ? <Empty>Loading…</Empty> : !list.length ? <Empty>{view === 'open' ? 'No open incidents. Normal stations do not open incidents.' : 'No incidents in this view.'}</Empty> : (
          <div className="lv-table-wrap sg-queue">
            <table className="lv-table">
              <thead><tr><th>Incident</th><th>Station</th><th>Sensor</th><th>Finding</th><th>Severity</th><th>Status</th><th>Detected</th></tr></thead>
              <tbody>
                {list.map((i) => {
                  const st = opsStatus(i);
                  return (
                    <tr key={i.incident_id} className={`clickable ${openIncidentId === i.incident_id ? 'selected' : ''}`} onClick={() => onOpenIncident(i.incident_id)}>
                      <td className="lv-mono" style={{ fontSize: '0.72rem' }}>{i.incident_id}</td>
                      <td>{i.station_name || i.station_id}{i.source === 'SIMULATED_FEED' && <div><SourceBadge simulated /></div>}</td>
                      <td>{i.parameter}</td>
                      <td>{i.context?.rca_label || human(i.root_cause)}</td>
                      <td><span className={`lv-pill lv-pill-sm ${i.severity === 'CRITICAL' ? 'lv-status-anomaly' : 'lv-status-suspect'}`}>{i.severity}</span></td>
                      <td><span className={`lv-pill lv-pill-sm ${TONE[st.tone]}`}>{st.label}</span></td>
                      <td className="lv-muted">{formatAge(i.detected_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {openIncidentId && (all || []).some((i) => i.incident_id === openIncidentId) && (
        <IncidentPanel key={openIncidentId} incidentId={openIncidentId} onChanged={load}
          onInvestigate={onInvestigate} onOpenStation={onOpenStation} onShowOnMap={onShowOnMap} />
      )}
    </div>
  );
};

const IncidentPanel: React.FC<{
  incidentId: string; onChanged: () => void;
  onInvestigate: (id: string) => void; onOpenStation: (id: string) => void; onShowOnMap: (id: string) => void;
}> = ({ incidentId, onChanged, onInvestigate, onOpenStation, onShowOnMap }) => {
  const [inc, setInc] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<'escalate' | 'resolve' | 'dismiss' | 'report' | null>(null);

  const load = () => fetchIncidentDetail(incidentId).then(setInc).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [incidentId]);
  useLiveEvents(['INCIDENT_UPDATED'], (e) => { if (e.data?.incident_id === incidentId) load(); });

  if (!inc) return <Empty>{error || 'Loading incident…'}</Empty>;

  const ctx = inc.context || {};
  const closed = isClosed(inc);
  const allowed = NEXT[inc.status] || [];
  const openWo = openWorkOrder(inc.work_orders);
  const layers = layerRows(inc);
  const contributing = layers.filter((l) => l.triggered);
  const act = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); await load(); onChanged(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <section className="lv-card">
        <div className="lv-card-body" style={{ padding: '18px 20px' }}>
          <div className="lv-spread" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div className="a-eyebrow">{inc.incident_id} · {opsStatus(inc).label}</div>
              <h2 className="a-h1" style={{ fontSize: '1.25rem' }}>{ctx.rca_label || human(inc.root_cause)} — {inc.station_name || inc.station_id}</h2>
            </div>
            <div className="lv-row">
              <span className={`lv-pill ${inc.severity === 'CRITICAL' ? 'lv-status-anomaly' : 'lv-status-suspect'}`}><span className="lv-dot" />{inc.severity}</span>
              {inc.source === 'SIMULATED_FEED' && <SourceBadge simulated />}
              <button className="lv-btn" onClick={() => onInvestigate(inc.incident_id)}><InvestigateIcon size={14} />Investigate</button>
              <button className="lv-btn" onClick={() => onOpenStation(inc.station_id)}>Open station</button>
              <button className="lv-btn" onClick={() => onShowOnMap(inc.station_id)}><MapPinned size={14} />Map</button>
              <button className="lv-btn lv-btn-primary" onClick={() => setModal('report')}><FileText size={14} />View report</button>
            </div>
          </div>

          <ol className="sg-stepper" aria-label="Incident lifecycle">
            {lifecycleSteps(inc).map((s) => (
              <li key={s.key} className={s.done ? 'done' : s.key === 'action' && openWo ? 'current' : ''}>
                <span className="sg-step-dot" />
                <span className="sg-step-label">{s.label}</span>
                <span className="sg-step-at">{s.at ? fmtDateTime(s.at) : '—'}</span>
                {s.note && <span className="sg-step-at">{s.note}</span>}
              </li>
            ))}
          </ol>
          {error && <div className="lv-callout danger" style={{ marginTop: 10 }}>{error}</div>}
        </div>
      </section>

      <div className="lv-grid-2">
        <Card title="What happened">
          <dl className="lv-kv">
            <dt>What</dt><dd>{ctx.summary || (inc.evidence || [])[0] || `${inc.parameter} anomaly`}</dd>
            <dt>Where</dt><dd>{inc.station_name || inc.station_id} <span className="lv-mono lv-muted">{inc.station_id}</span>{inc.region ? ` · ${inc.region}` : ''}</dd>
            <dt>When</dt><dd>{fmtDateTime(ctx.first_observation_at || inc.detected_at)} ({formatAge(ctx.first_observation_at || inc.detected_at)})</dd>
            <dt>Affected sensor</dt><dd>{inc.parameter}</dd>
            <dt>Why detected</dt><dd>{contributing.length ? contributing.map((l) => `${l.name}: ${l.reason}`).join(' · ') : (inc.evidence || []).join(' · ') || '—'}</dd>
            <dt>Severity</dt><dd>{inc.severity}{typeof inc.confidence === 'number' ? ` · evidence quality ${Math.round(inc.confidence * 100)}%*` : ''}</dd>
            <dt>Root cause</dt><dd>{ctx.rca_label || human(inc.root_cause)}</dd>
            <dt>What to do</dt><dd>{ctx.action_label ? <b>{ctx.action_label}: </b> : null}{inc.recommended_action || '—'}</dd>
          </dl>
          {typeof inc.confidence === 'number' && <p className="a-note" style={{ marginTop: 6 }}>* Heuristic evidence-quality score — not a calibrated probability.</p>}
        </Card>

        <Card title="Detection layers at detection">
          {!layers.length ? <Empty>Per-layer results were not captured with this incident.</Empty> : (
            <table className="lv-table">
              <thead><tr><th>Layer</th><th>Result</th><th>Evidence</th></tr></thead>
              <tbody>
                {layers.map((l) => (
                  <tr key={l.code}><td>{l.name}</td>
                    <td><span className={`lv-pill lv-pill-sm ${l.triggered ? 'lv-status-anomaly' : l.state === 'Nominal' ? 'lv-status-nominal' : 'lv-status-unknown'}`}>{l.state}</span></td>
                    <td className="lv-muted">{l.reason}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div className="lv-grid-2">
        <WorkOrderPanel inc={inc} busy={busy} act={act} />
        <Card title="Timeline">
          <ol className="lv-timeline">
            {timeline(inc).map((t, i) => (
              <li key={i}>
                <span className={`lv-tl-dot ${/RESOLVED|COMPLETED|RESTORED/.test(t.stage) ? 'ok' : /DETECTION|INCIDENT_CREATED/.test(t.stage) ? 'hit' : /ESCALAT|REVISED/.test(t.stage) ? 'warn' : ''}`} />
                <span><span className="lv-tl-stage">{human(t.stage)}</span><span className="lv-tl-at">{fmtDateTime(t.at)}{t.actor ? ` · ${t.actor}` : ''}</span>
                  {t.detail && <div className="lv-tl-text">{t.detail}</div>}</span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <Card title="Lifecycle actions">
        {closed ? (
          <div className="lv-callout ok">Closed ({inc.status.toLowerCase()}){inc.resolution_notes ? `: ${inc.resolution_notes}` : inc.dismissal_reason ? `: ${inc.dismissal_reason}` : ''}.</div>
        ) : (
          <>
            <div className="lv-row">
              <button className="lv-btn" disabled={busy || !allowed.includes('ACKNOWLEDGED')} onClick={() => act(() => acknowledgeIncident(inc.incident_id))}><UserCheck size={14} />Acknowledge</button>
              <button className="lv-btn" disabled={busy || !allowed.includes('INVESTIGATING')} onClick={() => act(() => investigateIncident(inc.incident_id))}><InvestigateIcon size={14} />Start investigating</button>
              <button className="lv-btn" disabled={busy || !allowed.includes('ESCALATED')} onClick={() => setModal('escalate')}><Siren size={14} />Escalate</button>
              <button className="lv-btn lv-btn-primary" disabled={busy || !allowed.includes('RESOLVED') || !!openWo} onClick={() => setModal('resolve')}><CheckCircle2 size={14} />Resolve</button>
              <button className="lv-btn lv-btn-danger" disabled={busy || !allowed.includes('DISMISSED')} onClick={() => setModal('dismiss')}><XCircle size={14} />Dismiss</button>
            </div>
            <p className="a-note" style={{ marginTop: 8 }}>
              {openWo ? `Resolve becomes available when work order ${openWo.work_order_id} is completed.`
                : !allowed.includes('RESOLVED') ? 'Acknowledge and start investigating before resolving.' : 'Resolve records the outcome; the incident report keeps the full record.'}
            </p>
          </>
        )}
      </Card>

      {modal === 'escalate' && <EscalationPreviewModal incidentId={inc.incident_id} onClose={() => setModal(null)} onEscalated={() => { load(); onChanged(); }} />}
      {modal === 'resolve' && <ResolveIncidentModal incidentId={inc.incident_id} onClose={() => setModal(null)}
        onResolve={async (notes, type) => { await act(() => resolveIncident(inc.incident_id, notes, type)); }} />}
      {modal === 'dismiss' && <DismissIncidentModal incidentId={inc.incident_id} onClose={() => setModal(null)}
        onDismiss={async (reason) => { await act(() => dismissIncident(inc.incident_id, reason)); }} />}
      {modal === 'report' && <IncidentReport inc={inc} onClose={() => setModal(null)} />}
    </div>
  );
};

const WorkOrderPanel: React.FC<{ inc: any; busy: boolean; act: (fn: () => Promise<any>) => Promise<void> }> = ({ inc, busy, act }) => {
  const ctx = inc.context || {};
  const open = openWorkOrder(inc.work_orders);
  const done = (inc.work_orders || []).filter((w: any) => w.status === 'COMPLETED');
  const [issue, setIssue] = useState(`${inc.parameter} sensor — ${ctx.rca_label || human(inc.root_cause)}`);
  const [priority, setPriority] = useState(PRIORITY_FROM_SEVERITY[inc.severity] || 'MEDIUM');
  const [team, setTeam] = useState('Field Maintenance');
  const [assignee, setAssignee] = useState('');
  const [note, setNote] = useState('');
  const next = open ? WO_NEXT[open.status] : undefined;

  return (
    <Card title="Maintenance work order" icon={<Wrench size={14} />}>
      {open ? (
        <>
          <dl className="lv-kv">
            <dt>Work order</dt><dd className="lv-mono">{open.work_order_id}</dd>
            <dt>Issue</dt><dd>{open.issue}</dd>
            <dt>Priority</dt><dd>{human(open.priority)}</dd>
            <dt>Team</dt><dd>{open.team}{open.assignee ? ` · ${open.assignee}` : ''}</dd>
            <dt>Status</dt><dd><b>{WO_LABEL[open.status]}</b> · updated {formatAge(open.updated_at)}</dd>
          </dl>
          <ol className="sg-stepper sg-stepper-sm">
            {['CREATED', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED'].map((s, i, arr) => (
              <li key={s} className={arr.indexOf(open.status) >= i ? 'done' : ''}><span className="sg-step-dot" /><span className="sg-step-label">{WO_LABEL[s]}</span></li>
            ))}
          </ol>
          {next && (
            <div className="lv-row" style={{ marginTop: 10 }}>
              {next === 'ASSIGNED' && <input className="a-input" placeholder="Assignee (technician or crew)" value={assignee} onChange={(e) => setAssignee(e.target.value)} />}
              {next === 'COMPLETED' && <input className="a-input" placeholder="Completion note (what was done)" value={note} onChange={(e) => setNote(e.target.value)} />}
              <button className="lv-btn lv-btn-primary" disabled={busy || (next === 'ASSIGNED' && !assignee.trim())}
                onClick={() => act(() => advanceWorkOrder(open.work_order_id, next, { assignee: assignee.trim() || undefined, note: note.trim() || undefined }))}>
                {next === 'ASSIGNED' ? 'Assign' : next === 'IN_PROGRESS' ? 'Start work' : 'Mark completed'}
              </button>
            </div>
          )}
        </>
      ) : isClosed(inc) ? (
        <Empty>{done.length ? `${done.length} work order(s) completed for this incident.` : 'No work order was raised for this incident.'}</Empty>
      ) : (
        <>
          {done.length > 0 && <p className="a-note" style={{ marginTop: 0 }}>{done.map((w: any) => `${w.work_order_id} completed ${fmtDateTime(w.completed_at)}`).join(' · ')}</p>}
          <div className="sg-form">
            <label>Issue<input className="a-input" value={issue} onChange={(e) => setIssue(e.target.value)} /></label>
            <label>Priority
              <select className="a-select" value={priority} onChange={(e) => setPriority(e.target.value)}>
                {['LOW', 'MEDIUM', 'HIGH', 'URGENT'].map((p) => <option key={p} value={p}>{human(p)}</option>)}
              </select>
            </label>
            <label>Assigned team<input className="a-input" value={team} onChange={(e) => setTeam(e.target.value)} /></label>
          </div>
          <div className="lv-row" style={{ marginTop: 10 }}>
            <button className="lv-btn lv-btn-primary" disabled={busy || !issue.trim() || !team.trim()}
              onClick={() => act(() => createWorkOrder(inc.incident_id, { issue: issue.trim(), priority, team: team.trim() }))}><Wrench size={14} />Create work order</button>
            <span className="a-note">Priority defaults from the incident severity ({inc.severity.toLowerCase()}).</span>
          </div>
        </>
      )}
    </Card>
  );
};
