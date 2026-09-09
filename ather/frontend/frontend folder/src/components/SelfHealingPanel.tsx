import React from 'react';
import { 
  AlertTriangle, 
  ArrowDown, 
  CheckCircle2, 
  Cpu, 
  Activity, 
  Thermometer, 
  Wrench 
} from 'lucide-react';

export function SelfHealingPanel() {
  return (
    <aside className="absolute right-4 top-[76px] bottom-4 z-30 hidden w-[310px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl xl:flex animate-in fade-in slide-in-from-right-4">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-4">
        <div>
          <div className="flex items-center gap-2">
            <Wrench className="h-4 w-4 text-amber-400" />
            <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-white">
              Self-Healing
            </h2>
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            Real-Time Sensor Imputation
          </p>
        </div>
        <div className="flex h-6 items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 text-[9px] font-bold text-amber-400">
          <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
          ACTIVE
        </div>
      </div>

      {/* Main Content - Scrollable */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        
        {/* Status Text */}
        <div className="text-[10px] leading-relaxed text-slate-400">
          ATHER automatically quarantines anomalous data streams and reconstructs missing values using Spatial IDW (Inverse Distance Weighting) and temporal continuity.
        </div>

        {/* Live Correction Card */}
        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black/40 p-4">
          
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Thermometer className="h-4 w-4 text-slate-400" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-300">
                AWS-77 (Temperature)
              </span>
            </div>
            <span className="text-[9px] text-slate-500 font-mono">Just now</span>
          </div>

          {/* Raw Value Block (Error State) */}
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-bold uppercase text-red-400">Raw Sensor Value</span>
              <AlertTriangle className="h-3 w-3 text-red-400" />
            </div>
            <div className="mt-1 flex items-end gap-2">
              <span className="font-mono text-2xl font-bold text-red-300">47.8°C</span>
              <span className="mb-1 text-[10px] text-red-400/70">Hardware Spike</span>
            </div>
          </div>

          {/* Processing Arrow & AI Logic */}
          <div className="relative my-2 flex flex-col items-center justify-center py-2">
            <div className="absolute top-0 bottom-0 w-px border-l-2 border-dashed border-slate-700" />
            <div className="relative z-10 flex items-center gap-2 rounded-full border border-cyan-500/30 bg-[#0f1720] px-3 py-1 shadow-[0_0_10px_rgba(34,211,238,0.1)]">
              <Cpu className="h-3.5 w-3.5 text-cyan-400" />
              <span className="text-[9px] font-bold uppercase tracking-wider text-cyan-300">
                Imputing Data
              </span>
            </div>
            <ArrowDown className="absolute bottom-0 h-4 w-4 text-slate-500 z-10 bg-[#0f1720]" />
          </div>

          {/* Corrected Value Block (Success State) */}
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3 relative overflow-hidden">
            <div className="absolute -right-4 -top-4 h-16 w-16 rounded-full bg-emerald-500/20 blur-xl" />
            <div className="relative flex items-center justify-between">
              <span className="text-[9px] font-bold uppercase text-emerald-400">Validated Value</span>
              <CheckCircle2 className="h-3 w-3 text-emerald-400" />
            </div>
            <div className="relative mt-1 flex items-end gap-2">
              <span className="font-mono text-2xl font-bold text-emerald-300">32.6°C</span>
              <div className="mb-1 flex flex-col">
                <span className="text-[9px] text-emerald-400/70">Expected: 32.4°C</span>
              </div>
            </div>
          </div>
        </div>

        {/* Action Log History */}
        <div>
          <h3 className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Recent Corrections
          </h3>
          <div className="space-y-2">
            <LogItem station="AWS-42" sensor="Humidity" original="0%" corrected="64%" />
            <LogItem station="AWS-19" sensor="Wind Speed" original="-15 km/h" corrected="12 km/h" />
          </div>
        </div>
      </div>

      {/* Footer - Sensor Health */}
      <div className="border-t border-white/10 bg-black/20 px-4 py-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5 text-slate-400" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
              AWS-77 Health Index
            </span>
          </div>
          <span className="font-mono text-xs font-bold text-amber-400">
            61%
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800/50">
          <div
            className="h-full rounded-full bg-gradient-to-r from-red-500 to-amber-400 transition-all duration-700 shadow-[0_0_8px_rgba(251,191,36,0.5)]"
            style={{ width: '61%' }}
          />
        </div>
        <div className="mt-2 text-right text-[9px] text-slate-500">
          Maintenance predicted in 14 days
        </div>
      </div>
      
    </aside>
  );
}

function LogItem({ station, sensor, original, corrected }: { station: string, sensor: string, original: string, corrected: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
      <div>
        <div className="text-[10px] font-bold text-slate-300">{station}</div>
        <div className="text-[9px] text-slate-500">{sensor}</div>
      </div>
      <div className="flex items-center gap-2 font-mono text-[10px]">
        <span className="text-red-400/80 line-through">{original}</span>
        <span className="text-slate-600">→</span>
        <span className="font-bold text-emerald-400">{corrected}</span>
      </div>
    </div>
  );
}