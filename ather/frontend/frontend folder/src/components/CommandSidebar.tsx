import React, { useState } from 'react';
import {
  Activity,
  BarChart3,
  BrainCircuit,
  ChevronDown,
  CloudRain,
  Layers,
  Map,
  RadioTower,
  ShieldCheck,
  Thermometer,
  Wind,
  Wrench,
} from 'lucide-react';

import type { WeatherLayerType } from '../types/weather';

interface CommandSidebarProps {
  activeLayer: WeatherLayerType;
  onSelectLayer: (layer: WeatherLayerType) => void;
  // Legacy anomaly props (kept for backward compatibility with App.tsx until updated)
  onSelectAnomalies?: () => void;
  isAnomalyActive?: boolean;
  // New unified navigation state
  activeView: string;
  onViewChange: (view: string) => void;
}

export const CommandSidebar: React.FC<CommandSidebarProps> = ({
  activeLayer,
  onSelectLayer,
  onSelectAnomalies,
  isAnomalyActive,
  activeView,
  onViewChange,
}) => {
  const [layersOpen, setLayersOpen] = useState(true);

  const weatherLayers: {
    id: WeatherLayerType;
    label: string;
    icon: React.ReactNode;
  }[] = [
    {
      id: 'radar',
      label: 'Weather Radar',
      icon: <CloudRain className="h-4 w-4 text-emerald-400" />,
    },
    {
      id: 'temp',
      label: 'Temperature',
      icon: <Thermometer className="h-4 w-4 text-amber-400" />,
    },
    {
      id: 'wind',
      label: 'Wind Flow',
      icon: <Wind className="h-4 w-4 text-cyan-400" />,
    },
    {
      id: 'pressure',
      label: 'Pressure',
      icon: <Activity className="h-4 w-4 text-violet-400" />,
    },
  ];

  return (
    <aside className="absolute left-4 top-[76px] bottom-4 z-30 hidden w-[230px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl lg:flex">
      {/* Brand */}
      <div className="border-b border-white/10 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 shadow-lg shadow-cyan-500/20">
            <RadioTower className="h-5 w-5 text-white" />
          </div>

          <div>
            <div className="text-sm font-black tracking-[0.18em] text-white">
              ATHER
            </div>
            <div className="text-[9px] font-semibold uppercase tracking-wider text-cyan-400">
              SkyGuard AI
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="mb-2 px-2 text-[9px] font-bold uppercase tracking-[0.18em] text-slate-500">
          Command Center
        </div>

        <nav className="space-y-1">
          <SidebarItem
            icon={<Map className="h-4 w-4" />}
            label="Overview"
            active={activeView === 'overview'}
            onClick={() => {
              onViewChange('overview');
              onSelectLayer('none');
            }}
          />

          <SidebarItem
            icon={<RadioTower className="h-4 w-4" />}
            label="Stations"
            active={activeView === 'stations'}
            onClick={() => onViewChange('stations')}
          />

          <SidebarItem
            icon={<ShieldCheck className="h-4 w-4" />}
            label="Anomalies"
            active={activeView === 'anomalies' || isAnomalyActive}
            danger={activeView === 'anomalies' || isAnomalyActive}
            onClick={() => {
              onViewChange('anomalies');
              if (onSelectAnomalies) onSelectAnomalies();
            }}
          />

          <SidebarItem
            icon={<BrainCircuit className="h-4 w-4" />}
            label="AI Insights"
            active={activeView === 'ai-insights'}
            onClick={() => onViewChange('ai-insights')}
          />

          <SidebarItem
            icon={<Wrench className="h-4 w-4" />}
            label="Self-Healing"
            active={activeView === 'self-healing'}
            onClick={() => onViewChange('self-healing')}
          />

          <SidebarItem
            icon={<BarChart3 className="h-4 w-4" />}
            label="Analytics"
            active={activeView === 'analytics'}
            onClick={() => onViewChange('analytics')}
          />
        </nav>

        {/* Weather Layers */}
        <div className="mt-6">
          <button
            onClick={() => setLayersOpen(!layersOpen)}
            className="flex w-full items-center justify-between px-2 py-2 text-left"
          >
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-slate-500" />
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-slate-500">
                Weather Layers
              </span>
            </div>

            <ChevronDown
              className={`h-3.5 w-3.5 text-slate-500 transition-transform ${
                layersOpen ? 'rotate-180' : ''
              }`}
            />
          </button>

          {layersOpen && (
            <div className="mt-1 space-y-1">
              {weatherLayers.map((layer) => {
                const active = activeLayer === layer.id;

                return (
                  <button
                    key={layer.id}
                    onClick={() => onSelectLayer(active ? 'none' : layer.id)}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs transition-all ${
                      active
                        ? 'border border-cyan-400/20 bg-cyan-400/10 text-white'
                        : 'text-slate-400 hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    {layer.icon}

                    <span className="flex-1">{layer.label}</span>

                    {active && (
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-white/10 p-3">
        <div className="rounded-xl bg-emerald-500/5 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>

            <span className="text-[10px] font-semibold text-emerald-300">
              System Operational
            </span>
          </div>

          <div className="mt-1 pl-4 text-[9px] text-slate-500">
            Live telemetry active
          </div>
        </div>
      </div>
    </aside>
  );
};

interface SidebarItemProps {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  danger?: boolean;
  onClick?: () => void;
}

const SidebarItem: React.FC<SidebarItemProps> = ({
  icon,
  label,
  active = false,
  danger = false,
  onClick,
}) => {
  return (
    <button
      onClick={onClick}
      className={`group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs transition-all ${
        active
          ? danger
            ? 'bg-red-500/10 text-red-300 ring-1 ring-red-400/20'
            : 'bg-cyan-400/10 text-cyan-300 ring-1 ring-cyan-400/20'
          : 'text-slate-400 hover:bg-white/5 hover:text-white'
      }`}
    >
      <span
        className={`transition-transform group-hover:scale-110 ${
          active ? 'text-current' : ''
        }`}
      >
        {icon}
      </span>

      <span className="font-medium">{label}</span>

      {active && (
        <span
          className={`ml-auto h-1.5 w-1.5 rounded-full ${
            danger ? 'bg-red-400' : 'bg-cyan-400'
          }`}
        />
      )}
    </button>
  );
};