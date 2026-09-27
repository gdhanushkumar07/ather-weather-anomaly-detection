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

/** The four product destinations. Station detail and System are reached
 *  from inside the product (a station, the live indicator), not as tabs. */
const TABS: { id: Workspace; label: string; also?: Workspace[] }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'map', label: 'Live Map', also: ['station'] },
  { id: 'anomalies', label: 'Investigations' },
  { id: 'testlab', label: 'Test Lab' },
];

export const TopNav: React.FC<TopNavProps> = ({ activeWorkspace, onNavigate, onSelectStation }) => {
  const { connection, lastEventAt, incidentCounts } = useLive();
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

  const age = lastEventAt ? Math.round((now - lastEventAt) / 1000) : null;
  const live = connection === 'live' && age !== null && age < 30;
  const label = connection === 'offline' ? 'OFFLINE' : connection !== 'live' ? 'CONNECTING' : live ? 'LIVE' : 'NO RECENT DATA';
  const open_ = incidentCounts?.active ?? 0;

  return (
    <header className="a-nav">
      <button className="a-brand" onClick={() => onNavigate('home')} title="ATHER home">
        <span className="a-brand-mark" />
        <span style={{ textAlign: 'left' }}>
          <span className="a-brand-name">ATHER</span>
          <span className="a-brand-sub">Weather intelligence</span>
        </span>
      </button>

      <nav className="a-tabs" aria-label="ATHER">
        {TABS.map((t) => {
          const active = activeWorkspace === t.id || !!t.also?.includes(activeWorkspace);
          return (
            <button key={t.id} className={`a-tab ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => onNavigate(t.id)}>
              {t.label}
              {t.id === 'anomalies' && open_ > 0 && <span className="a-tab-count" title="Open investigations">{open_}</span>}
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
        <button className="a-live" onClick={() => onNavigate('system')} title="Pipeline and data-source health">
          <span className={`lv-live-dot ${live ? '' : connection === 'offline' ? 'off' : 'wait'}`} />
          {label}{age !== null && connection === 'live' ? ` · ${age}s` : ''}
        </button>
      </div>
    </header>
  );
};
