import React, { useState, useEffect, useRef } from 'react';
import { Search, Activity, AlertTriangle, Radio } from 'lucide-react';
import { Station, AnomaliesSummary } from '../types/weather';
import { searchStations } from '../services/api';

interface TopNavProps {
  summary: AnomaliesSummary | null;
  onSelectStation: (stationId: string) => void;
  statusFilter: string | null;
  onSetStatusFilter: (status: string | null) => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  summary,
  onSelectStation,
  statusFilter,
  onSetStatusFilter
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
    <header className="ather-navbar">
      {/* Brand Identity */}
      <div className="brand-section">
        <div className="brand-logo">
          <Radio className="brand-logo-icon" />
          <span>ATHER</span>
        </div>
        <span className="brand-badge">Station Intelligence</span>
      </div>

      {/* Center Search Input */}
      <div className="search-container" ref={dropdownRef}>
        <Search className="search-icon w-4 h-4" />
        <input
          type="text"
          className="search-input"
          placeholder="Search station or city (e.g. Hyderabad)..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={() => results.length > 0 && setIsOpen(true)}
        />

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
                  <div style={{ fontWeight: 600, color: '#0f172a' }}>{stn.name}</div>
                  <div style={{ fontSize: '0.74rem', color: '#64748b', marginTop: 1 }}>
                    {stn.id} · {stn.town}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span
                    className={`stat-pill ${stn.status.toLowerCase()}`}
                    style={{ fontSize: '0.68rem', padding: '2px 6px' }}
                  >
                    {stn.status}
                  </span>
                  {stn.temperature !== null && stn.temperature !== undefined && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem', fontWeight: 600, marginTop: 2 }}>
                      {stn.temperature} °C
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Live Status KPIs */}
      <div className="nav-stats">
        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(null)}
          title="Click to show all stations"
        >
          <span className="stat-pill all">
            <Activity className="w-3.5 h-3.5 text-slate-500" />
            <span>Stations: {summary?.totalStations ?? 1655}</span>
          </span>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'NORMAL' ? null : 'NORMAL')}
          title="Filter by Normal"
        >
          <span className="stat-pill normal">
            <span className="stat-dot-small" />
            <span>{summary?.normalCount ?? 1607} Normal</span>
          </span>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'WARNING' ? null : 'WARNING')}
          title="Filter by Warning"
        >
          <span className="stat-pill warning">
            <AlertTriangle className="w-3 h-3 text-amber-600" />
            <span>{summary?.warningCount ?? 3} Warning</span>
          </span>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'ANOMALY' ? null : 'ANOMALY')}
          title="Filter by Anomaly"
        >
          <span className="stat-pill anomaly">
            <AlertTriangle className="w-3 h-3 text-red-600" />
            <span>{summary?.anomalyCount ?? 45} Anomaly</span>
          </span>
        </div>
      </div>
    </header>
  );
};
