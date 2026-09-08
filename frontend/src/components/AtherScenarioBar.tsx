import React from 'react';
import { AtherDemoScenario } from '../types';
import { 
  Play, 
  Pause, 
  Sparkles, 
  AlertCircle, 
  ShieldCheck, 
  Flame, 
  Snowflake, 
  TrendingDown, 
  Zap,
  Info
} from 'lucide-react';

interface AtherScenarioBarProps {
  currentScenario: AtherDemoScenario;
  onSelectScenario: (scenario: AtherDemoScenario) => void;
  isStreaming: boolean;
  onToggleStreaming: () => void;
  totalStations: number;
  criticalCount: number;
  warningCount: number;
  healthyCount: number;
  onOpenArchitectureModal: () => void;
}

export const AtherScenarioBar: React.FC<AtherScenarioBarProps> = ({
  currentScenario,
  onSelectScenario,
  isStreaming,
  onToggleStreaming,
  totalStations,
  criticalCount,
  warningCount,
  healthyCount,
  onOpenArchitectureModal,
}) => {
  const scenarios: {
    id: AtherDemoScenario;
    label: string;
    icon: React.ReactNode;
    tag: string;
    description: string;
  }[] = [
    {
      id: 'hyd_spike',
      label: 'Hyd Spike (+25°C)',
      icon: <Zap size={12} className="text-rose-400" />,
      tag: 'Sensor Spike',
      description: 'Physical Impossibility & Isolated Sensor Failure',
    },
    {
      id: 'genuine_heatwave',
      label: 'Genuine Heatwave',
      icon: <Flame size={12} className="text-amber-400" />,
      tag: 'False-Alarm Filter',
      description: 'Regional Spatial Consensus confirms real event',
    },
    {
      id: 'frozen_sensor',
      label: 'Frozen Sensor',
      icon: <Snowflake size={12} className="text-cyan-400" />,
      tag: 'Flatline',
      description: 'Zero variance over 3 hours (Delhi)',
    },
    {
      id: 'sensor_drift',
      label: 'Calibration Drift',
      icon: <TrendingDown size={12} className="text-purple-400" />,
      tag: 'Degradation',
      description: 'Slow continuous calibration creep (Mumbai)',
    },
    {
      id: 'unphysical_combo',
      label: 'Unphysical State',
      icon: <AlertCircle size={12} className="text-yellow-400" />,
      tag: 'Thermodynamics',
      description: '42°C with 98% RH impossible psychrometric state',
    },
    {
      id: 'normal',
      label: 'Nominal Network',
      icon: <ShieldCheck size={12} className="text-emerald-400" />,
      tag: 'Healthy',
      description: 'All 12 AWS stations within nominal bounds',
    },
  ];

  return (
    <div
      id="ather-scenario-bar"
      className="fixed top-14 left-1/2 -translate-x-1/2 z-[990] flex items-center gap-2 bg-[#121620]/90 backdrop-blur-md border border-slate-700/80 rounded-full px-3 py-1.5 shadow-2xl text-xs select-none pointer-events-auto"
    >
      {/* ATHER Brand Pill */}
      <div className="flex items-center gap-1.5 pl-1 pr-2 border-r border-slate-700/70">
        <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
        <span className="font-extrabold text-white tracking-wider text-[11px]">
          ATHER
        </span>
        <span className="hidden lg:inline text-[9px] font-mono text-sky-300/80 bg-sky-950/60 px-1 py-0.2 rounded border border-sky-800/40">
          5-LAYER AI
        </span>
      </div>

      {/* Scenario Dropdown / Quick Buttons */}
      <div className="flex items-center gap-1">
        <span className="hidden md:inline text-[10px] font-semibold uppercase text-slate-400 mr-0.5">
          SIH Scenarios:
        </span>
        <div className="flex items-center gap-1 overflow-x-auto max-w-[420px] sm:max-w-[560px] no-scrollbar py-0.5">
          {scenarios.map((sc) => {
            const isSelected = currentScenario === sc.id;
            return (
              <button
                key={sc.id}
                id={`scenario-btn-${sc.id}`}
                onClick={() => onSelectScenario(sc.id)}
                title={`${sc.label}: ${sc.description}`}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[10.5px] font-medium whitespace-nowrap transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-sky-500 text-white font-bold shadow-md shadow-sky-500/20 scale-102'
                    : 'bg-slate-800/60 text-slate-300 hover:bg-slate-700/80 hover:text-white border border-slate-700/50'
                }`}
              >
                {sc.icon}
                <span>{sc.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Live Stream Telemetry Toggle */}
      <div className="flex items-center gap-1.5 pl-1.5 border-l border-slate-700/70">
        <button
          id="toggle-telemetry-stream-btn"
          onClick={onToggleStreaming}
          className={`flex items-center gap-1 px-2 py-1 rounded-full text-[10.5px] font-mono font-semibold transition-all cursor-pointer ${
            isStreaming
              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/30'
              : 'bg-slate-800/80 text-slate-400 border border-slate-700 hover:text-white'
          }`}
          title={isStreaming ? 'Pause live AWS telemetry stream' : 'Resume live telemetry simulation'}
        >
          {isStreaming ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              <Pause size={10} />
              <span className="hidden sm:inline">Streaming (3s)</span>
            </>
          ) : (
            <>
              <Play size={10} />
              <span className="hidden sm:inline">Stream Paused</span>
            </>
          )}
        </button>

        {/* Network Health Stats */}
        <div className="hidden xl:flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900/60 border border-slate-800">
          <span className="text-slate-400">{totalStations} AWS</span>
          <span className="text-slate-600">|</span>
          <span className="text-emerald-400">{healthyCount} OK</span>
          {warningCount > 0 && (
            <>
              <span className="text-slate-600">|</span>
              <span className="text-amber-400">{warningCount} Warn</span>
            </>
          )}
          {criticalCount > 0 && (
            <>
              <span className="text-slate-600">|</span>
              <span className="text-rose-400 font-bold animate-pulse">{criticalCount} Critical</span>
            </>
          )}
        </div>

        {/* Architecture Info Button */}
        <button
          id="open-ather-arch-modal-btn"
          onClick={onOpenArchitectureModal}
          className="p-1 rounded-full text-slate-400 hover:text-sky-300 hover:bg-slate-800 transition-colors"
          title="Inspect ATHER 5-Layer AI Architecture Details"
        >
          <Info size={14} />
        </button>
      </div>
    </div>
  );
};
