import React, { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { Station } from '../types/weather';
import { searchStations } from '../services/api';
import { Workspace } from '../types/workspace';
import { useLive } from '../services/live';

interface TopNavProps {
  activeWorkspace: Workspace;
  onNavigate: (workspace: Workspace) => void;
  onSelectStation: (stationId: string) => void;
}

/** The five product destinations. Station detail and System are reached
 *  from inside the product (a station, the live indicator), not as tabs. */
const TABS: { id: Workspace; label: string; also?: Workspace[] }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'map', label: 'Live Map', also: ['station'] },
  { id: 'incidents', label: 'Incidents' },
  { id: 'anomalies', label: 'Investigations' },
  { id: 'testlab', label: 'Test Lab' },
];

export const TopNav: React.FC<TopNavProps> = ({ activeWorkspace, onNavigate, onSelectStation }) => {
  const { connection, lastEventAt, incidentCounts, system } = useLive();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Station[]>([]);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    const t = setTimeout(() => searchStations(q).then((r) => { setResults(r); setOpen(r.length > 0); }).catch(() => {}), 150);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  // Two separate facts: is the server reachable (SSE heartbeat every 5 s),
  // and is TELEMETRY fresh (age of the newest processed observation vs the
  // source cadence). "LIVE" requires both; a connected server with old data
  // says STALE DATA and how old it is.
  const hbAge = lastEventAt ? Math.round((now - lastEventAt) / 1000) : null;
  const connected = connection === 'live' && hbAge !== null && hbAge < 30;
  const newest = system?.metrics?.newest_observation_epoch as number | null | undefined;
  const cadence = Math.max(60, ...((system?.sources || []).filter((s: any) => s.kind !== 'REFERENCE' && (s.state === 'ACTIVE' || s.state === 'DEGRADED')).map((s: any) => s.cadence_s || 0)));
  const age = newest ? Math.max(0, Math.round(now / 1000 - newest)) : null;
  const fresh = age !== null && age <= 3 * cadence;
  const live = connected && fresh;
  const label = connection === 'offline' ? 'OFFLINE' : connection !== 'live' ? 'CONNECTING' : !connected ? 'NO RECENT DATA' : age === null ? 'NO TELEMETRY' : fresh ? 'LIVE' : 'STALE DATA';
  const ageText = age === null ? '' : age < 120 ? `${age}s` : age < 7200 ? `${Math.round(age / 60)}m` : `${Math.round(age / 3600)}h`;
  const open_ = incidentCounts?.active ?? 0;

  return (
    <header className="a-nav">
      <button className="a-brand" onClick={() => onNavigate('home')} title="SkyGuard AI home">
        <span className="a-brand-mark" />
        <span style={{ textAlign: 'left' }}>
          <span className="a-brand-name">SkyGuard AI</span>
          <span className="a-brand-sub">Weather intelligence</span>
        </span>
      </button>

      <nav className="a-tabs" aria-label="SkyGuard AI">
        {TABS.map((t) => {
          const active = activeWorkspace === t.id || !!t.also?.includes(activeWorkspace);
          return (
            <button key={t.id} className={`a-tab ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => onNavigate(t.id)}>
              {t.label}
              {t.id === 'incidents' && open_ > 0 && <span className="a-tab-count" title="Open incidents">{open_}</span>}
            </button>
          );
        })}
      </nav>

      <div className="a-nav-right">
        <div className="a-search" ref={boxRef}>
          <Search size={14} />
          <input value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => results.length && setOpen(true)}
            placeholder="Find station by name or ID" aria-label="Find station" />
          {open && (
            <div className="a-search-menu">
              {results.map((s) => (
                <button key={s.id} className="a-search-item" onClick={() => { onSelectStation(s.id); setOpen(false); setQ(''); }}>
                  <span>
                    <div style={{ fontWeight: 700, fontSize: '0.8rem' }}>{s.name}</div>
                    <div className="lv-mono" style={{ fontSize: '0.66rem', color: 'var(--a-ink-3)' }}>{s.id} · {s.town}</div>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="a-live" onClick={() => onNavigate('system')} title="Telemetry freshness = age of the newest processed observation (expected every source cadence). Click for pipeline and data-source health.">
          <span className={`lv-live-dot ${live ? '' : connection === 'offline' ? 'off' : 'wait'}`} />
          {label}{connected && age !== null ? ` · data ${ageText} old` : ''}
        </button>
      </div>
    </header>
  );
};
