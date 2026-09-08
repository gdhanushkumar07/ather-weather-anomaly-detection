import React from 'react';
import { 
  X, 
  Layers, 
  Activity, 
  Compass, 
  Cpu, 
  ShieldCheck, 
  RotateCcw, 
  HelpCircle,
  CheckCircle2,
  AlertTriangle
} from 'lucide-react';

interface AtherArchitectureModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AtherArchitectureModal: React.FC<AtherArchitectureModalProps> = ({
  isOpen,
  onClose,
}) => {
  if (!isOpen) return null;

  const layers = [
    {
      num: 1,
      name: 'Physical Law Validation',
      subtitle: 'Atmospheric Physics & Thermodynamic Bounds',
      color: 'border-sky-500/80 bg-sky-950/20 text-sky-400',
      description:
        'Evaluates atmospheric thermodynamic invariants: Dew Point cannot exceed Dry Bulb (T_dew <= T), Barometric pressure limits with barometric lapse formula, and maximum physical rate-of-change thresholds (|dT/dt| <= 5°C/15min).',
      formulas: 'T_dew ≤ T_dry | SLP = P · (1 - 0.0065·h / 288.15)^-5.255',
    },
    {
      num: 2,
      name: 'Temporal Intelligence',
      subtitle: 'MOMENT Foundation Model & Multi-Scale Statistics',
      color: 'border-indigo-500/80 bg-indigo-950/20 text-indigo-400',
      description:
        'Combines zero-shot time-series foundation model representations with rolling Z-score, IQR, and flatline detection. Catches sudden spikes, step discontinuities, and frozen sensors (zero variance over hours).',
      formulas: 'Z = (x - μ_24h) / σ_24h | IQR = Q3 - Q1 | Var(window) < ε',
    },
    {
      num: 3,
      name: 'Multivariate Consistency',
      subtitle: 'Cross-Sensor Correlation & Psychrometrics',
      color: 'border-purple-500/80 bg-purple-950/20 text-purple-400',
      description:
        'Validates physical coupling between co-located sensors: Temperature surge must correlate with Relative Humidity drop. Wet-bulb calculation verifies psychrometric consistency across environmental state vectors.',
      formulas: 'Cov(T, RH) < 0 | e_s(T) = 6.112 · exp((17.67·T)/(T+243.5))',
    },
    {
      num: 4,
      name: 'Spatial Intelligence (False-Alarm Killer)',
      subtitle: 'Spatial Consensus via Inverse Distance Weighting (IDW)',
      color: 'border-amber-500/80 bg-amber-950/20 text-amber-400',
      description:
        'The core innovation that prevents false alarms during extreme meteorological events: Computes elevation-corrected IDW consensus across k-nearest stations. If neighbors also show high heat, it is a genuine heatwave; if isolated, it is a sensor fault.',
      formulas: 'T_consensus = Σ (w_i · (T_i - Γ·Δh)) / Σ w_i,  w_i = 1 / d_i^p',
    },
    {
      num: 5,
      name: 'Sensor Health & Drift',
      subtitle: 'Continuous Calibration Creep & Lifecycle Monitoring',
      color: 'border-emerald-500/80 bg-emerald-950/20 text-emerald-400',
      description:
        'Tracks cumulative bias against spatial consensus over rolling windows. Computes CUSUM (cumulative sum control chart) to detect slow sensor drift (+0.3°C/day) before catastrophic failure occurs.',
      formulas: 'S_t = max(0, S_{t-1} + (x_t - μ - k)) | Health% = 100 - Degradation',
    },
  ];

  return (
    <div
      id="ather-architecture-modal-backdrop"
      className="fixed inset-0 z-[1200] bg-black/75 backdrop-blur-md flex items-center justify-center p-4 select-none"
      onClick={onClose}
    >
      <div
        id="ather-architecture-modal"
        className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-[#141824] border border-slate-700/80 rounded-2xl shadow-2xl p-6 text-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-700/60 pb-4 mb-4">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-lg bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center text-white text-xs font-black shadow">
                A
              </div>
              <h2 className="text-lg font-bold text-white tracking-wide">
                ATHER Architecture
              </h2>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-sky-950 border border-sky-600/50 text-sky-300">
                SIH SOLUTION
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 font-mono">
              Autonomous Environmental Twin with Hierarchical Ensemble Reasoning
            </p>
          </div>
          <button
            id="close-ather-modal-btn"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Core Philosophy Banner */}
        <div className="p-3 rounded-xl bg-slate-800/60 border border-slate-700/80 mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="text-sky-400 font-bold">Pipeline:</span>
            <span className="text-slate-300">Observe</span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">Detect</span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">Reason</span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-300">Explain</span>
            <span className="text-slate-500">→</span>
            <span className="text-emerald-400 font-bold">Self-Heal</span>
          </div>
          <span className="text-[10px] text-slate-400">Bayesian Evidence Fusion</span>
        </div>

        {/* 5-Layer Stack */}
        <div className="space-y-3 mb-6">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">
            The 5-Layer Intelligence Model
          </h3>
          {layers.map((layer) => (
            <div
              key={layer.num}
              className={`p-3.5 rounded-xl border ${layer.color} transition-all`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-slate-900 border border-slate-700 flex items-center justify-center font-mono font-bold text-xs">
                    {layer.num}
                  </span>
                  <span className="font-bold text-sm text-white">
                    {layer.name}
                  </span>
                </div>
                <span className="text-[10px] font-mono opacity-80">
                  {layer.subtitle}
                </span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed mb-2">
                {layer.description}
              </p>
              <div className="font-mono text-[10.5px] bg-black/40 px-2.5 py-1 rounded border border-white/5 text-slate-300">
                {layer.formulas}
              </div>
            </div>
          ))}
        </div>

        {/* Self-Healing & Explainable AI highlights */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-3 border-t border-slate-700/60">
          <div className="p-3 bg-slate-800/40 rounded-xl border border-slate-700/60">
            <div className="flex items-center gap-1.5 font-bold text-xs text-emerald-400 mb-1">
              <RotateCcw size={14} />
              <span>Self-Healing Data Pipeline</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Original raw measurements are strictly preserved for audit trails.
              The system generates a parallel <strong className="text-slate-200">AI ESTIMATE</strong> stream via elevation-corrected IDW consensus and uncorrupted sensors.
            </p>
          </div>

          <div className="p-3 bg-slate-800/40 rounded-xl border border-slate-700/60">
            <div className="flex items-center gap-1.5 font-bold text-xs text-amber-400 mb-1">
              <HelpCircle size={14} />
              <span>Explainable AI (XAI)</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Every decision outputs deterministic physical violation logs, spatial agreement coefficients, and clear actionable maintenance recommendations for field engineers.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-5 pt-3 border-t border-slate-700/60 flex items-center justify-between text-[11px] text-slate-500 font-mono">
          <span>ATHER Engine v2.4</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-medium transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
