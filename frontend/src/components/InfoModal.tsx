import React from 'react';
import { X, Info, Wind, ShieldAlert, Cpu, Database } from 'lucide-react';

interface InfoModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const InfoModal: React.FC<InfoModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[1300] flex items-center justify-center bg-black/70 backdrop-blur-md p-4 pointer-events-auto">
      <div className="w-full max-w-lg bg-[#1b2028] border border-white/15 rounded-2xl shadow-2xl p-5 flex flex-col gap-4 text-slate-200 animate-in fade-in zoom-in duration-200">
        <div className="flex items-center justify-between pb-3 border-b border-white/10">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-[#e5283c] flex items-center justify-center text-white font-bold text-sm">
              🌀
            </div>
            <h2 className="font-bold text-white text-base">About ATHER Weather Intelligence</h2>
          </div>
          <button
            id="close-info-modal-btn"
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-white/10 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4 text-xs leading-relaxed max-h-[70vh] overflow-y-auto pr-1">
          <div>
            <h3 className="font-semibold text-white flex items-center gap-1.5 mb-1 text-sm">
              <Wind className="w-4 h-4 text-sky-400" />
              Dynamic Vector Streamlines & Turbulence
            </h3>
            <p className="text-slate-300">
              The wind particle animation runs at 60 FPS on HTML5 Canvas using vector calculus models representing the Somali Low-Level Jet, Indian Ocean Monsoon trough, Tropical Cyclone circulation, and high-altitude Rossby planetary waves.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-white flex items-center gap-1.5 mb-1 text-sm">
              <Database className="w-4 h-4 text-amber-400" />
              Global Numerical Weather Prediction (NWP)
            </h3>
            <ul className="list-disc list-inside space-y-1 text-slate-300">
              <li><strong className="text-white">ECMWF IFS (9 km):</strong> European Centre for Medium-Range Weather Forecasts (World standard for global synoptic scale).</li>
              <li><strong className="text-white">NOAA GFS (22 km):</strong> Global Forecast System by the US National Weather Service.</li>
              <li><strong className="text-white">DWD ICON (13 km):</strong> German Weather Service high-resolution non-hydrostatic global model.</li>
            </ul>
          </div>

          <div>
            <h3 className="font-semibold text-white flex items-center gap-1.5 mb-1 text-sm">
              <ShieldAlert className="w-4 h-4 text-red-400" />
              SIH AI Anomaly Detection Engine
            </h3>
            <p className="text-slate-300">
              Detects extreme meteorological anomalies using thermodynamic gradients (CAPE, vorticity, surface pressure falls) and classifies risk levels from D0 (Abnormally Dry) to D5 (Exceptional Cyclonic Surge).
            </p>
          </div>
        </div>

        <div className="pt-3 border-t border-white/10 flex justify-end">
          <button
            id="dismiss-info-modal-btn"
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-white font-semibold text-xs transition-colors cursor-pointer"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};
