import React, { useState, useEffect, useRef } from 'react';
import { Search, Activity, AlertTriangle, ShieldCheck, Radio } from 'lucide-react';
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
    }, 200);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Click outside to close dropdown
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
      {/* Brand */}
      <div className="brand-section">
        <div className="brand-logo">
          <Radio className="w-5 h-5" style={{ color: '#0284c7' }} />
          <span>ATHER</span>
        </div>
        <span className="brand-badge">Station Intelligence</span>
      </div>

      {/* Search Bar */}
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
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    {stn.id} · {stn.town}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span
                    className={`stat-pill ${stn.status.toLowerCase()}`}
                    style={{ fontSize: '0.7rem' }}
                  >
                    {stn.status}
                  </span>
                  {stn.temperature !== null && stn.temperature !== undefined && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', marginTop: 2 }}>
                      {stn.temperature} °C
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Anomaly & Status Metrics */}
      <div className="nav-stats">
        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(null)}
          title="Click to reset filter"
        >
          <Activity className="w-4 h-4 text-slate-400" />
          <span>Stations:</span>
          <strong>{summary?.totalStations || '1,655'}</strong>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'NORMAL' ? null : 'NORMAL')}
        >
          <ShieldCheck className="w-4 h-4" style={{ color: '#10b981' }} />
          <span className="stat-pill normal">
            {summary?.normalCount ?? 1607} Normal
          </span>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'WARNING' ? null : 'WARNING')}
        >
          <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} />
          <span className="stat-pill warning">
            {summary?.warningCount ?? 3} Warning
          </span>
        </div>

        <div
          className="stat-chip"
          style={{ cursor: 'pointer' }}
          onClick={() => onSetStatusFilter(statusFilter === 'ANOMALY' ? null : 'ANOMALY')}
        >
          <AlertTriangle className="w-4 h-4" style={{ color: '#ef4444' }} />
          <span className="stat-pill anomaly">
            {summary?.anomalyCount ?? 45} Anomaly
          </span>
        </div>
      </div>
    </header>
  );
};
