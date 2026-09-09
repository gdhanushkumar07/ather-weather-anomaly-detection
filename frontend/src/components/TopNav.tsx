import React, { useState, useEffect, useRef } from 'react';
import { Search, Activity, AlertTriangle, Radio, Wifi, Heart, ShieldAlert, ArrowUpRight, FlaskConical } from 'lucide-react';
import { Station, AnomaliesSummary } from '../types/weather';
import { searchStations } from '../services/api';

interface TopNavProps {
  summary: AnomaliesSummary | null;
  onSelectStation: (stationId: string) => void;
  statusFilter: string | null;
  onSetStatusFilter: (status: string | null) => void;
  onOpenTestLab?: () => void;
  onToggleOverview?: () => void;
  isOverviewOpen?: boolean;
}

export const TopNav: React.FC<TopNavProps> = ({
  summary,
  onSelectStation,
  statusFilter,
  onSetStatusFilter,
  onOpenTestLab,
  onToggleOverview,
  isOverviewOpen = false
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

      {/* Navigation Section Pills */}
      <div className="nav-capsule section-pills">
        {onToggleOverview && (
          <button
            className={`nav-section-btn overview-toggle-btn ${isOverviewOpen ? 'active' : ''}`}
            onClick={onToggleOverview}
            title="Toggle Network & Weather Overview panel"
          >
            <Activity className="w-3.5 h-3.5 text-cyan-400" />
            <span>Overview</span>
          </button>
        )}

        <button
          className={`nav-section-btn ${statusFilter === null && !isOverviewOpen ? 'active' : ''}`}
          onClick={() => onSetStatusFilter(null)}
          title="Show all network stations"
        >
          <Wifi className="w-3.5 h-3.5" />
          <span>Network</span>
        </button>

        <button
          className={`nav-section-btn ${statusFilter === 'ANOMALY' ? 'active alert' : ''}`}
          onClick={() => onSetStatusFilter(statusFilter === 'ANOMALY' ? null : 'ANOMALY')}
          title="Filter anomaly stations"
        >
          <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
          <span>Anomalies</span>
          {summary?.anomalyCount !== undefined && summary.anomalyCount > 0 ? (
            <span className="nav-badge-count anomaly">{summary.anomalyCount}</span>
          ) : null}
        </button>

        <button
          className={`nav-section-btn ${statusFilter === 'WARNING' ? 'active warn' : ''}`}
          onClick={() => onSetStatusFilter(statusFilter === 'WARNING' ? null : 'WARNING')}
          title="Filter warning & sensor health status"
        >
          <Heart className="w-3.5 h-3.5 text-amber-400" />
          <span>Sensor Health</span>
          {summary?.warningCount !== undefined && summary.warningCount > 0 ? (
            <span className="nav-badge-count warning">{summary.warningCount}</span>
          ) : null}
        </button>

        {onOpenTestLab && (
          <button
            className="nav-section-btn test-lab-launch-btn"
            onClick={onOpenTestLab}
            title="Open ATHER Diagnostic Test Lab — validate the engine with simulated fault scenarios"
          >
            <FlaskConical className="w-3.5 h-3.5 text-slate-400" />
            <span>Test Lab</span>
          </button>
        )}
      </div>

      {/* Live Telemetry KPI Pills — Data-driven, no magic fallback numbers */}
      <div className="nav-capsule live-stats-capsule">
        <div className="live-pill">
          <span className="live-dot-pulse" />
          <span>LIVE</span>
        </div>

        <div className="stat-pill-item total" onClick={() => onSetStatusFilter(null)} title="Filter All Stations">
          <span className="stat-label">Stations:</span>
          <span className="stat-val">{summary?.totalStations ?? '--'}</span>
        </div>

        <div
          className={`stat-pill-item normal ${statusFilter === 'NORMAL' ? 'selected' : ''}`}
          onClick={() => onSetStatusFilter(statusFilter === 'NORMAL' ? null : 'NORMAL')}
          title="Filter Normal"
        >
          <span className="stat-bullet green" />
          <span>{summary?.normalCount ?? '--'} Normal</span>
        </div>

        <div
          className={`stat-pill-item warning ${statusFilter === 'WARNING' ? 'selected' : ''}`}
          onClick={() => onSetStatusFilter(statusFilter === 'WARNING' ? null : 'WARNING')}
          title="Filter Warning"
        >
          <span className="stat-bullet amber" />
          <span>{summary?.warningCount ?? '--'} Warning</span>
        </div>

        <div
          className={`stat-pill-item anomaly ${statusFilter === 'ANOMALY' ? 'selected' : ''}`}
          onClick={() => onSetStatusFilter(statusFilter === 'ANOMALY' ? null : 'ANOMALY')}
          title="Filter Anomaly"
        >
          <span className="stat-bullet red" />
          <span>{summary?.anomalyCount ?? '--'} Anomaly</span>
        </div>
      </div>
    </header>
  );
};
