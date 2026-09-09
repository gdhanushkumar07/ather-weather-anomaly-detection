import React from 'react';
import { 
  AlertOctagon, 
  BarChart3, 
  CalendarClock, 
  TrendingUp, 
  Activity 
} from 'lucide-react';

export function AnalyticsPanel() {
  return (
    <aside className="absolute right-4 top-[76px] bottom-4 z-30 hidden w-[310px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl xl:flex animate-in fade-in slide-in-from-right-4">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-4">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-emerald-400" />
            <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-white">
              System Analytics
            </h2>
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            Network Trends & Maintenance
          </p>
        </div>
      </div>

      {/* Main Content - Scrollable */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        
        {/* KPI Row */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
            <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">System Accuracy</div>
            <div className="mt-1 flex items-end gap-2">
              <span className="font-mono text-xl font-bold text-white">98.4%</span>
              <span className="mb-1 flex items-center text-[9px] text-emerald-400">
                <TrendingUp className="mr-0.5 h-3 w-3" /> +1.2%
              </span>
            </div>
          </div>
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
            <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500">Anomalies (24h)</div>
            <div className="mt-1 flex items-end gap-2">
              <span className="font-mono text-xl font-bold text-amber-400">127</span>
              <span className="mb-1 flex items-center text-[9px] text-slate-500">
                Avg: 110
              </span>
            </div>
          </div>
        </div>

        {/* 24h Anomaly Distribution (Pure Tailwind "Chart") */}
        <div>
          <h3 className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5" />
            Anomaly Distribution
          </h3>
          <div className="space-y-3 rounded-xl border border-white/5 bg-black/20 p-4">
            <DistributionBar label="Temperature Spikes" value={45} color="bg-red-400" />
            <DistributionBar label="Wind Sensor Frozen" value={28} color="bg-cyan-400" />
            <DistributionBar label="Humidity Drift" value={15} color="bg-blue-400" />
            <DistributionBar label="Pressure Drop" value={12} color="bg-emerald-400" />
          </div>
        </div>

        {/* Predictive Maintenance Alerts */}
        <div>
          <h3 className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
            <CalendarClock className="h-3.5 w-3.5" />
            Predictive Maintenance
          </h3>
          <div className="space-y-2">
            
            <div className="flex items-center justify-between rounded-lg border border-red-500/20 bg-red-500/10 p-3">
              <div className="flex items-center gap-3">
                <AlertOctagon className="h-4 w-4 text-red-400" />
                <div>
                  <div className="text-[10px] font-bold text-white">AWS-12 (Mumbai)</div>
                  <div className="text-[9px] text-red-300">Anemometer bearing failure</div>
                </div>
              </div>
              <div className="text-right">
                <div className="font-mono text-[10px] font-bold text-red-400">2 DAYS</div>
                <div className="text-[8px] uppercase text-red-400/60">To Failure</div>
              </div>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
              <div className="flex items-center gap-3">
                <AlertOctagon className="h-4 w-4 text-amber-500" />
                <div>
                  <div className="text-[10px] font-bold text-white">AWS-88 (Delhi)</div>
                  <div className="text-[9px] text-amber-500/80">Barometer recalibration req.</div>
                </div>
              </div>
              <div className="text-right">
                <div className="font-mono text-[10px] font-bold text-amber-500">5 DAYS</div>
                <div className="text-[8px] uppercase text-amber-500/60">To Failure</div>
              </div>
            </div>

          </div>
        </div>

      </div>
    </aside>
  );
}

function DistributionBar({ label, value, color }: { label: string, value: number, color: string }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-[9px]">
        <span className="text-slate-300">{label}</span>
        <span className="font-mono font-bold text-white">{value}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
        <div 
          className={`h-full rounded-full ${color} transition-all duration-1000 ease-out`} 
          style={{ width: `${value}%` }} 
        />
      </div>
    </div>
  );
}