import React, { useState, useEffect, useRef } from 'react';
import { Search, Activity, Map as MapIcon, ShieldAlert, HeartPulse, FlaskConical, Radio, ArrowUpRight, Cpu } from 'lucide-react';
import { useLive } from '../services/live';
import { Station, AnomaliesSummary } from '../types/weather';
import { searchStations } from '../services/api';
import { Workspace } from '../types/workspace';

interface TopNavProps {
  summary: AnomaliesSummary | null;
  activeIncidentCounts?: Record<string, number> | null;
  onSelectStation: (stationId: string) => void;
  activeWorkspace: Workspace;
  onNavigate: (workspace: Workspace) => void;
  lastUpdatedAt?: number | null;
}

function formatAge(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

const WORKSPACE_TABS: { id: Workspace; label: string; icon: React.ComponentType<{ size?: number; className?: string }> }[] = [
  { id: 'map', label: 'Command Center', icon: MapIcon },
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'anomalies', label: 'Incidents', icon: ShieldAlert },
  { id: 'health', label: 'Sensor Health', icon: HeartPulse },
  { id: 'testlab', label: 'Test Lab', icon: FlaskConical },
  { id: 'system', label: 'System', icon: Cpu },
];

export const TopNav: React.FC<TopNavProps> = ({
  summary,
  activeIncidentCounts,
  onSelectStation,
  activeWorkspace,
  onNavigate,
  lastUpdatedAt = null
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [results, setResults] = useState<Station[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setResults([]);
      setIsOpen(false);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await searchStations(searchQuery);
        setResults(res);
        setIsOpen(res.length > 0);
      } catch (err) {
        console.error(err);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Re-render the data-age label once a second
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // LIVE means: the SSE stream is connected AND an event arrived recently —
  // not merely that a page request once succeeded.
  const { connection, lastEventAt, counts } = useLive();
  const liveAge = lastEventAt ?? lastUpdatedAt;
  const isStale = connection !== 'live' || liveAge == null || now - liveAge > 30_000;
  const liveLabel = connection === 'live' ? (isStale ? 'STALE' : 'LIVE') : connection === 'offline' ? 'OFFLINE' : 'CONNECTING';

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="ather-unified-header-wrapper">
      <header className="ather-unified-navbar">
        {/* Left: Brand Identity */}
        <div
          className="brand-identity-container"
          onClick={() => onNavigate('home')}
          role="button"
          tabIndex={0}
          title="Return to ATHER Homepage"
        >
          <div className="brand-icon-box">
            <span className="brand-dot-pulse" />
            <Radio className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <div className="brand-text-group">
            <span className="brand-main-title">ATHER</span>
            <span className="brand-tag-divider">|</span>
            <span className="brand-sub-tag">STATION INTELLIGENCE</span>
          </div>
        </div>

        {/* Center: Cohesive Navigation Tabs */}
        <nav className="unified-nav-tabs" aria-label="ATHER workspaces">
          {WORKSPACE_TABS.map(({ id, label, icon: Icon }) => {
            const isActive = activeWorkspace === id;
            return (
              <button
                key={id}
                className={`unified-tab-btn ${isActive ? 'active' : ''}`}
                onClick={() => onNavigate(id)}
                aria-current={isActive ? 'page' : undefined}
                title={label}
              >
                <Icon size={14} className={isActive ? 'text-blue-600' : 'text-slate-500'} />
                <span>{label}</span>
                {id === 'anomalies' && activeIncidentCounts?.active ? (
                  <span className="tab-badge-pill anomaly" title="Active incidents">
                    {activeIncidentCounts.active}
                  </span>
                ) : null}
                {id === 'health' && counts && (counts.suspect || counts.degraded) ? (
                  <span className="tab-badge-pill warning">{(counts.suspect || 0) + (counts.degraded || 0)}</span>
                ) : null}
              </button>
            );
          })}
        </nav>

        {/* Right: Integrated Search + Live State */}
        <div className="unified-nav-right">
          <div className="unified-search-box" ref={dropdownRef}>
            <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <input
              type="text"
              className="unified-search-input"
              placeholder="Search station, city or station ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => results.length > 0 && setIsOpen(true)}
            />
            <div className="search-enter-hint">
              <ArrowUpRight className="w-3 h-3 text-slate-400" />
            </div>

            {isOpen && (
              <div className="search-dropdown">
                {results.map((stn) => (
                  <div
                    key={stn.id}
                    className="search-item"
                    onClick={() => {
                      onSelectStation(stn.id);
                      setIsOpen(false);
                      setSearchQuery('');
                    }}
                  >
                    <div>
                      <div className="search-stn-name">{stn.name}</div>
                      <div className="search-stn-meta">
                        {stn.id} · {stn.town}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span className={`stat-pill ${stn.status.toLowerCase()}`}>
                        {stn.status}
                      </span>
                      {stn.temperature !== null && stn.temperature !== undefined && (
                        <div className="search-stn-temp">
                          {stn.temperature} °C
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className={`unified-live-badge ${isStale ? 'stale' : ''}`} title="Server-sent event stream from the ATHER pipeline">
            <span className="live-dot-pulse" />
            <span>{liveLabel}</span>
          </div>
        </div>
      </header>

      {/* Sub-Header: Real-Time Telemetry & Status Strip */}
      <div className="unified-status-substrip">
        <div className="substrip-left">
          <span className="substrip-live-text">
            <span className="substrip-dot" />
            {connection !== 'live' ? 'EVENT STREAM ' + liveLabel : isStale ? 'NO RECENT EVENTS' : 'LIVE DETECTION STREAM'}
          </span>
          {liveAge != null && (
            <span className="substrip-age">
              Last event: {formatAge(now - liveAge)}
            </span>
          )}
        </div>

        <div className="substrip-stats-row">
          <div className="substrip-stat-item" onClick={() => onNavigate('map')} title="Stations processed by the live pipeline">
            <span className="stat-count">{counts?.live_stations?.toLocaleString() ?? '—'}</span>
            <span className="stat-name">Live stations</span>
          </div>
          <span className="substrip-divider">·</span>
          <div className="substrip-stat-item normal" onClick={() => onNavigate('map')} title="Nominal">
            <span className="stat-dot green" />
            <span className="stat-count">{counts?.nominal?.toLocaleString() ?? '—'}</span>
            <span className="stat-name">Nominal</span>
          </div>
          <span className="substrip-divider">·</span>
          <div className="substrip-stat-item warning" onClick={() => onNavigate('health')} title="Suspect or degraded">
            <span className="stat-dot amber" />
            <span className="stat-count">{counts ? ((counts.suspect || 0) + (counts.degraded || 0)).toLocaleString() : '—'}</span>
            <span className="stat-name">Suspect / degraded</span>
          </div>
          <span className="substrip-divider">·</span>
          <div className="substrip-stat-item anomaly" onClick={() => onNavigate('anomalies')} title="Anomalous">
            <span className="stat-dot red" />
            <span className="stat-count">{counts?.anomaly?.toLocaleString() ?? '—'}</span>
            <span className="stat-name">Anomaly</span>
          </div>
        </div>
      </div>
    </div>
  );
};
