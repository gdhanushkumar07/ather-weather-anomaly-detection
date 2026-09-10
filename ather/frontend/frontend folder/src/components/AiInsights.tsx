import React from 'react';
import { 
  Activity, 
  BrainCircuit, 
  Clock, 
  Map, 
  Network, 
  Thermometer, 
  TrendingDown 
} from 'lucide-react';

export function AiInsights(){
  return (
    <aside className="absolute right-4 top-[76px] bottom-4 z-30 hidden w-[310px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl xl:flex animate-in fade-in slide-in-from-right-4">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-4">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-cyan-400" />
            <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-white">
              AI Insights
            </h2>
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            5-Layer Anomaly Detection Pipeline
          </p>
        </div>
      </div>

      {/* Pipeline Visualization */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        
        {/* Layer 1 */}
        <PipelineLayer 
          number="01"
          title="Physics Validation"
          description="Thermodynamic bounds checking via MetPy."
          icon={<Thermometer className="h-4 w-4 text-emerald-400" />}
          active
        />

        {/* Arrow */}
        <div className="flex justify-center -my-2 relative z-0">
          <div className="w-px h-6 bg-gradient-to-b from-emerald-500/50 to-cyan-500/50" />
        </div>

        {/* Layer 2 */}
        <PipelineLayer 
          number="02"
          title="Temporal Analysis"
          description="Rate-of-change & frozen sensor detection."
          icon={<Clock className="h-4 w-4 text-cyan-400" />}
          active
        />

        {/* Arrow */}
        <div className="flex justify-center -my-2 relative z-0">
          <div className="w-px h-6 bg-cyan-500/50" />
        </div>

        {/* Layer 3 */}
        <PipelineLayer 
          number="03"
          title="Multivariate ECOD"
          description="PyOD-based empirical cumulative distribution."
          icon={<Network className="h-4 w-4 text-cyan-400" />}
          active
        />

        {/* Arrow */}
        <div className="flex justify-center -my-2 relative z-0">
          <div className="w-px h-6 bg-cyan-500/50" />
        </div>

        {/* Layer 4 */}
        <PipelineLayer 
          number="04"
          title="Spatial Consensus"
          description="IDW & nearby AWS neighbor comparison."
          icon={<Map className="h-4 w-4 text-cyan-400" />}
          active
        />

        {/* Arrow */}
        <div className="flex justify-center -my-2 relative z-0">
          <div className="w-px h-6 bg-gradient-to-b from-cyan-500/50 to-amber-500/50" />
        </div>

        {/* Layer 5 */}
        <PipelineLayer 
          number="05"
          title="CUSUM Drift Detection"
          description="Cumulative sum predictive maintenance."
          icon={<TrendingDown className="h-4 w-4 text-amber-400" />}
          active
        />

      </div>

      {/* Footer Capstone */}
      <div className="border-t border-cyan-500/30 bg-cyan-950/30 px-4 py-4 relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-900/40 via-transparent to-transparent" />
        <div className="relative flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-[0_0_10px_rgba(34,211,238,0.2)]">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-[11px] font-bold text-white uppercase tracking-wider">
              Conformal Evidence Fusion
            </h3>
            <p className="mt-1 text-[9px] text-slate-400 leading-relaxed">
              Combines p-values from all 5 layers to generate a final, calibrated confidence score and XAI root-cause classification.
            </p>
          </div>
        </div>
      </div>
      
    </aside>
  );
}

function PipelineLayer({
  number,
  title,
  description,
  icon,
  active
}: {
  number: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  active?: boolean;
}) {
  return (
    <div className={`relative flex gap-3 rounded-xl border p-3 z-10 bg-[#0f1720] ${
      active 
        ? 'border-white/10 shadow-lg shadow-black/50' 
        : 'border-white/5 opacity-50'
    }`}>
      <div className="flex flex-col items-center gap-1">
        <div className="text-[9px] font-bold text-slate-500">{number}</div>
        <div className="rounded-full bg-white/5 p-1.5">
          {icon}
        </div>
      </div>
      <div className="flex-1 py-1">
        <h3 className="text-xs font-bold text-slate-200">{title}</h3>
        <p className="mt-1 text-[10px] text-slate-500">{description}</p>
      </div>
    </div>
  );
}