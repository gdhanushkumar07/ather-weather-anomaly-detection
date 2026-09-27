import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { PipelineModel, Stage, CONFIDENCE_NOTE } from '../../utils/pipeline';

/**
 * The ATHER intelligence pipeline for ONE observation, in the order the
 * backend evaluates it: OBSERVE → DETECT → FUSE → EXPLAIN → ACT.
 * Each row answers: what does this stage check · what did it find · how did it
 * contribute. Rows expand to the raw evidence the backend reported.
 */

const STATE_CLASS: Record<string, string> = {
  pass: 'lv-status-nominal',
  warning: 'lv-status-suspect',
  triggered: 'lv-status-anomaly',
  unassessed: 'lv-status-degraded',
  decision: 'lv-status-unknown',
  neutral: 'lv-status-weather',
};

const DECISION_CLASS: Record<string, string> = {
  nominal: 'lv-status-nominal', suspect: 'lv-status-suspect', degraded: 'lv-status-degraded',
  anomaly: 'lv-status-anomaly', weather: 'lv-status-weather',
};

const StageRow: React.FC<{ s: Stage; open: boolean; onToggle: () => void }> = ({ s, open, onToggle }) => {
  const cls = s.tone === 'decision' ? DECISION_CLASS[s.state] || 'lv-status-unknown' : STATE_CLASS[s.tone];
  const hasBody = s.evidence.length > 0 || s.notes.length > 0 || !!s.checks;
  return (
    <div className={`a-step ${s.tone === 'triggered' ? 'triggered' : s.tone === 'warning' ? 'warning' : s.tone === 'unassessed' ? 'unassessed' : s.tone === 'decision' ? 'decision' : ''}`}>
      <button className="a-step-head" onClick={onToggle} aria-expanded={open}>
        <span className="a-step-num">{String(s.n).padStart(2, '0')}</span>
        <span className="a-step-name">{s.name}</span>
        <span><span className={`lv-pill lv-pill-sm ${cls}`}><span className="lv-dot" />{s.state}</span></span>
        <span className="a-step-finding">{s.finding}</span>
        <span className="a-step-contrib">
          {s.contribution && <b>{s.contribution}</b>}
          {hasBody && (open ? <ChevronDown size={14} style={{ verticalAlign: -3, marginLeft: 6 }} /> : <ChevronRight size={14} style={{ verticalAlign: -3, marginLeft: 6 }} />)}
        </span>
      </button>
      {open && hasBody && (
        <div className="a-step-body">
          <div className="a-note">Checks: {s.checks}</div>
          {s.evidence.length > 0 && (
            <div className="a-evidence">
              {s.evidence.map(([k, v], i) => <div key={i}><span>{k}</span><b>{v}</b></div>)}
            </div>
          )}
          {s.notes.map((n, i) => <div key={i} className="a-note">{n}</div>)}
        </div>
      )}
    </div>
  );
};

export const IntelligencePipeline: React.FC<{ model: PipelineModel; expandAll?: boolean; hideConfidenceNote?: boolean }> = ({ model, expandAll, hideConfidenceNote }) => {
  const initial = () => {
    const o: Record<string, boolean> = {};
    model.phases.forEach((p) => p.stages.forEach((s) => {
      o[s.key] = !!expandAll || s.tone === 'triggered' || s.tone === 'warning';
    }));
    return o;
  };
  const [open, setOpen] = useState<Record<string, boolean>>(initial);
  // Keep user's expansion state across live refreshes; open newly triggered stages.
  useEffect(() => {
    setOpen((prev) => {
      const next = { ...prev };
      model.phases.forEach((p) => p.stages.forEach((s) => {
        if ((s.tone === 'triggered' || s.tone === 'warning') && next[s.key] === undefined) next[s.key] = true;
      }));
      return next;
    });
  }, [model]);

  const all = Object.values(open).every(Boolean);
  return (
    <div>
      <div className="lv-spread" style={{ marginBottom: 10 }}>
        <span className="a-note">{model.phases[1].stages.filter((s) => s.tone !== 'unassessed').length} of 5 detection layers assessed this observation · scores are evidence scores, not probabilities</span>
        <button className="lv-link" style={{ fontSize: '0.74rem' }} onClick={() => {
          const v = !all; const o: Record<string, boolean> = {};
          model.phases.forEach((p) => p.stages.forEach((s) => { o[s.key] = v; }));
          setOpen(o);
        }}>{all ? 'Collapse all' : 'Expand all'}</button>
      </div>
      <div className="a-pipe">
        {model.phases.map((p) => (
          <div key={p.id} className="a-pipe-phase">
            <div className="a-pipe-phase-label"><b>{p.id}</b>{p.question}</div>
            <div className="a-pipe-steps">
              {p.stages.map((s) => (
                <StageRow key={s.key} s={s} open={!!open[s.key]} onToggle={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {model.headline.confidence !== null && !hideConfidenceNote && <p className="a-note" style={{ marginTop: 8 }}>* {CONFIDENCE_NOTE}</p>}
    </div>
  );
};
