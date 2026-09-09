import React, { useEffect, useState, useMemo } from 'react';
import {
  RadioTower,
  Search,
  CheckCircle2,
  AlertTriangle,
  Thermometer,
  Droplets,
  MapPin,
} from 'lucide-react';
import { fetchAtherStations } from '../utils/api';
import type { AtherStationData, AtherStationsResponse } from '../types/weather';

interface StationsPanelProps {
  onSelectStation?: (station: AtherStationData) => void;
}

export function StationsPanel({ onSelectStation }: StationsPanelProps) {
  const [data, setData] = useState<AtherStationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

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

  const filteredStations = useMemo(() => {
    if (!data?.stations) return [];
    return data.stations.filter((station) => {
      const query = searchQuery.toLowerCase();
      const name = (station.name || '').toLowerCase();
      const id = (station.station_id || '').toLowerCase();
      return name.includes(query) || id.includes(query);
    });
  }, [data, searchQuery]);

  return (
    <aside className="absolute right-4 top-[76px] bottom-4 z-30 hidden w-[310px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl xl:flex animate-in fade-in slide-in-from-right-4">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-4">
        <div>
          <div className="flex items-center gap-2">
            <RadioTower className="h-4 w-4 text-blue-400" />
            <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-white">
              Network Stations
            </h2>
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            Active AWS Node Registry
          </p>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-bold text-white">
            {data?.station_count || 0}
          </div>
          <div className="text-[9px] uppercase tracking-wider text-slate-500">
            Total Nodes
          </div>
        </div>
      </div>

      {/* Search Bar */}
      <div className="border-b border-white/10 bg-black/10 p-3">
        <div className="relative flex items-center rounded-lg border border-white/10 bg-black/20 px-3 py-1.5 focus-within:border-blue-400/50">
          <Search className="h-3.5 w-3.5 text-slate-400 shrink-0" />
          <input
            type="text"
            placeholder="Search stations by name or ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="ml-2 w-full bg-transparent text-xs text-white placeholder-slate-500 outline-none"
          />
        </div>
      </div>

      {/* Station List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && !data ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((item) => (
              <div key={item} className="h-16 animate-pulse rounded-xl bg-white/5" />
            ))}
          </div>
        ) : filteredStations.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-500">
            No stations found matching "{searchQuery}"
          </div>
        ) : (
          filteredStations.map((station) => {
            const isAnomaly = station.anomaly?.is_anomaly;
            const temp = station.weather?.temperature_c;
            const humidity = station.weather?.humidity_pct; // Fixed to match your actual types!

            return (
              <button
                key={station.station_id}
                onClick={() => onSelectStation?.(station)}
                className="group flex w-full items-center justify-between rounded-xl border border-white/5 bg-white/[0.02] p-3 text-left transition-all hover:bg-white/[0.05] hover:border-blue-500/30"
              >
                <div className="flex items-center gap-3">
                  {/* Status Indicator */}
                  <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-black/40 border border-white/5">
                    {isAnomaly ? (
                      <AlertTriangle className="h-4 w-4 text-amber-400" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    )}
                  </div>
                  
                  {/* Name & ID */}
                  <div>
                    <div className="text-xs font-bold text-slate-200 group-hover:text-blue-300 transition-colors">
                      {station.name || station.station_id}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1 text-[9px] text-slate-500">
                      <MapPin className="h-2.5 w-2.5" />
                      {station.lat.toFixed(2)}, {station.lon.toFixed(2)}
                    </div>
                  </div>
                </div>

                {/* Mini Telemetry */}
                <div className="text-right flex flex-col items-end gap-1">
                  <div className="flex items-center gap-1 font-mono text-[10px] text-slate-300">
                    {temp !== undefined ? `${temp.toFixed(1)}°C` : '--'}
                    <Thermometer className="h-3 w-3 text-slate-500" />
                  </div>
                  <div className="flex items-center gap-1 font-mono text-[10px] text-slate-400">
                    {humidity !== undefined ? `${humidity.toFixed(0)}%` : '--'}
                    <Droplets className="h-3 w-3 text-slate-500" />
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}