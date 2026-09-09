import React, { useState, useEffect, useRef } from 'react';
import { Search, Activity, Map as MapIcon, ShieldAlert, HeartPulse, FlaskConical, Radio, ArrowUpRight } from 'lucide-react';
import { Station, AnomaliesSummary } from '../types/weather';
import { searchStations } from '../services/api';
import { Workspace } from '../types/workspace';

interface TopNavProps {
  summary: AnomaliesSummary | null;
  onSelectStation: (stationId: string) => void;
  activeWorkspace: Workspace;
  onNavigate: (workspace: Workspace) => void;
}

const WORKSPACE_TABS: { id: Workspace; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'map', label: 'Map', icon: MapIcon },
  { id: 'anomalies', label: 'Anomalies', icon: ShieldAlert },
  { id: 'health', label: 'Sensor Health', icon: HeartPulse },
  { id: 'testlab', label: 'Test Lab', icon: FlaskConical },
];

export const TopNav: React.FC<TopNavProps> = ({
  summary,
  onSelectStation,
  activeWorkspace,
  onNavigate
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
    <header className="ather-navbar-wrapper">
      {/* Brand Capsule */}
      <div className="nav-capsule brand-capsule">
        <div className="brand-logo">
          <div className="brand-icon-wrapper">
            <span className="brand-dot-pulse" />
            <Radio className="brand-logo-icon" />
          </div>
          <span className="brand-name">ATHER</span>
        </div>
        <span className="brand-divider">|</span>
        <span className="brand-tag">STATION INTELLIGENCE</span>
      </div>

      {/* Center Search Capsule */}
      <div className="search-capsule" ref={dropdownRef}>
        <Search className="search-icon w-4 h-4" />
        <input
          type="text"
          className="search-input"
          placeholder="Search station or city..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={() => results.length > 0 && setIsOpen(true)}
        />
        <div className="search-action-btn">
          <ArrowUpRight className="w-3.5 h-3.5 text-slate-400" />
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

      {/* Primary Workspace Navigation — the app's information architecture,
          not a set of map filters. Exactly one workspace is active at a time. */}
      <nav className="nav-capsule section-pills workspace-tabs" aria-label="ATHER workspaces">
        {WORKSPACE_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`nav-section-btn workspace-tab-btn ${activeWorkspace === id ? 'active' : ''}`}
            onClick={() => onNavigate(id)}
            aria-current={activeWorkspace === id ? 'page' : undefined}
            title={label}
          >
            <Icon className="w-3.5 h-3.5" />
            <span>{label}</span>
            {id === 'anomalies' && summary?.anomalyCount ? (
              <span className="nav-badge-count anomaly">{summary.anomalyCount}</span>
            ) : null}
            {id === 'health' && summary?.warningCount ? (
              <span className="nav-badge-count warning">{summary.warningCount}</span>
            ) : null}
          </button>
        ))}
      </nav>

      {/* Live Telemetry KPI Strip — read-only network snapshot, always visible
          regardless of workspace. Clicking a count navigates to the workspace
          where that state is actually managed. */}
      <div className="nav-capsule live-stats-capsule">
        <div className="live-pill">
          <span className="live-dot-pulse" />
          <span>LIVE</span>
        </div>

        <div className="stat-pill-item total" onClick={() => onNavigate('map')} title="Open Map">
          <span className="stat-label">Stations:</span>
          <span className="stat-val">{summary?.totalStations ?? '--'}</span>
        </div>

        <div className="stat-pill-item normal" onClick={() => onNavigate('map')} title="Open Map">
          <span className="stat-bullet green" />
          <span>{summary?.normalCount ?? '--'} Normal</span>
        </div>

        <div className="stat-pill-item warning" onClick={() => onNavigate('health')} title="Open Sensor Health">
          <span className="stat-bullet amber" />
          <span>{summary?.warningCount ?? '--'} Warning</span>
        </div>

        <div className="stat-pill-item anomaly" onClick={() => onNavigate('anomalies')} title="Open Anomalies">
          <span className="stat-bullet red" />
          <span>{summary?.anomalyCount ?? '--'} Anomaly</span>
        </div>
      </div>
    </header>
  );
};
