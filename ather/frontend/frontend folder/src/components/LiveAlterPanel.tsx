import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  RadioTower,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react';

import { fetchAtherStations } from '../utils/api';

import type {
  AtherStationData,
  AtherStationsResponse,
} from '../types/weather';

interface LiveAlertPanelProps {
  onSelectStation?: (station: AtherStationData) => void;
}

export function LiveAlertPanel({
  onSelectStation,
}: LiveAlertPanelProps) {
  const [data, setData] = useState<AtherStationsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const loadStations = async () => {
    try {
      const result = await fetchAtherStations();
      setData(result);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStations();
    const interval = window.setInterval(loadStations, 10000);
    return () => window.clearInterval(interval);
  }, []);

  const anomalies = useMemo(() => {
    if (!data?.stations) return [];
    return data.stations
      .filter((station) => station.anomaly?.is_anomaly)
      .sort(
        (a, b) =>
          b.anomaly.confidence_score - a.anomaly.confidence_score
      )
      .slice(0, 5);
  }, [data]);

  const totalStations = data?.station_count ?? 0;
  const healthyStations = data?.healthy_count ?? 0;
  const anomalyCount = data?.anomaly_count ?? 0;

  const health =
    totalStations > 0
      ? Math.round((healthyStations / totalStations) * 1000) / 10
      : 0;

  return (
    <aside className="absolute right-4 top-[76px] bottom-4 z-30 hidden w-[310px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl xl:flex">
      
      {/* Header - Fixed internal padding and removed broken 'fixed' positioning */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-red-400" />
            </span>
            <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-white">
              Live Intelligence
            </h2>
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            ATHER anomaly monitoring
          </p>
        </div>

        <button
          onClick={loadStations}
          className="rounded-lg p-2 text-slate-400 transition hover:bg-white/10 hover:text-cyan-300"
          title="Refresh"
        >
          <RefreshCw
            className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}
          />
        </button>
      </div>

      {/* KPI strip - Centered items */}
      <div className="grid grid-cols-3 divide-x divide-white/5 border-b border-white/10 bg-black/10">
        <MiniStat
          label="Stations"
          value={formatNumber(totalStations)}
          icon={<RadioTower className="h-3.5 w-3.5" />}
        />
        <MiniStat
          label="Healthy"
          value={formatNumber(healthyStations)}
          icon={<CheckCircle2 className="h-3.5 w-3.5" />}
          positive
        />
        <MiniStat
          label="Alerts"
          value={formatNumber(anomalyCount)}
          icon={<ShieldAlert className="h-3.5 w-3.5" />}
          danger={anomalyCount > 0}
        />
      </div>

      {/* Health */}
      <div className="border-b border-white/10 px-4 py-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
            Network health
          </span>
          <span className="font-mono text-xs font-bold text-emerald-300">
            {health}%
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800/50 inset-shadow">
          <div
            className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-700 shadow-[0_0_8px_rgba(52,211,153,0.5)]"
            style={{ width: `${Math.min(100, health)}%` }}
          />
        </div>
      </div>

      {/* Alerts */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Active anomalies
          </span>
          <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[9px] font-bold text-red-400 border border-red-500/20">
            {anomalyCount} detected
          </span>
        </div>

        {loading && !data ? (
          <div className="space-y-2">
            {[1, 2, 3].map((item) => (
              <div
                key={item}
                className="h-20 animate-pulse rounded-xl bg-white/5"
              />
            ))}
          </div>
        ) : anomalies.length === 0 ? (
          <div className="rounded-xl border border-emerald-400/10 bg-emerald-400/5 p-6 text-center">
            <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-400" />
            <div className="mt-3 text-xs font-semibold text-emerald-300">
              All stations healthy
            </div>
            <div className="mt-1 text-[10px] text-slate-500">
              No active anomalies detected
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            {anomalies.map((station) => (
              <AlertCard
                key={station.station_id}
                station={station}
                onClick={() => onSelectStation?.(station)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-white/10 bg-black/20 px-4 py-3">
        <div className="flex items-center justify-between text-[9px] text-slate-500 font-medium">
          <div className="flex items-center gap-1.5">
            <Clock3 className="h-3.5 w-3.5" />
            Auto-refresh: 10s
          </div>
          <span className="flex items-center gap-1.5 text-cyan-400">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
            LIVE
          </span>
        </div>
      </div>
    </aside>
  );
}

function AlertCard({
  station,
  onClick,
}: {
  station: AtherStationData;
  onClick: () => void;
}) {
  const critical = station.anomaly.confidence_score >= 0.8;
  const confidence = Math.round(station.anomaly.confidence_score * 100);

  return (
    <button
      onClick={onClick}
      className={`group w-full rounded-xl border p-3.5 text-left transition-all hover:-translate-y-0.5 ${
        critical
          ? 'border-red-400/20 bg-red-500/[0.06] hover:border-red-400/40 shadow-lg shadow-red-500/5'
          : 'border-amber-400/20 bg-amber-500/[0.05] hover:border-amber-400/40 shadow-lg shadow-amber-500/5'
      }`}
    >
      <div className="flex items-start gap-3">
        <div
          className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
            critical
              ? 'bg-red-500/10 text-red-400'
              : 'bg-amber-500/10 text-amber-400'
          }`}
        >
          <AlertTriangle className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xs font-bold text-white group-hover:text-cyan-300 transition-colors">
              {station.name || station.station_id}
            </span>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500 transition group-hover:text-cyan-400 group-hover:translate-x-0.5" />
          </div>
          <div className="mt-1 text-[9px] text-slate-400">
            {station.station_id}
          </div>
          <div className="mt-2.5 flex items-center justify-between">
            <span
              className={`text-[9px] font-bold uppercase tracking-wider ${
                critical ? 'text-red-300' : 'text-amber-300'
              }`}
            >
              {station.anomaly.root_cause?.replaceAll('_', ' ').toLowerCase()}
            </span>
            <span className="font-mono text-[9px] text-slate-400">
              {confidence}% conf
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

function MiniStat({
  label,
  value,
  icon,
  positive,
  danger,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  positive?: boolean;
  danger?: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center p-3 text-center">
      <div className="flex items-center gap-1.5 text-slate-500 mb-1.5">
        {icon}
        <span className="text-[9px] uppercase tracking-wider font-semibold">
          {label}
        </span>
      </div>
      <div
        className={`font-mono text-sm font-bold ${
          danger
            ? 'text-red-400'
            : positive
              ? 'text-emerald-400'
              : 'text-white'
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function formatNumber(value: number) {
  return value.toLocaleString('en-IN');
}