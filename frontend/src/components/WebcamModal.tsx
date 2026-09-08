import React from 'react';
import { X, MapPin, Video, ExternalLink, Calendar, RefreshCw } from 'lucide-react';
import { WebcamItem } from '../types';

interface WebcamModalProps {
  webcam: WebcamItem | null;
  onClose: () => void;
}

export const WebcamModal: React.FC<WebcamModalProps> = ({ webcam, onClose }) => {
  if (!webcam) return null;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
      <div 
        id="webcam-preview-modal"
        className="bg-[#1a1e26] border border-white/15 rounded-2xl shadow-2xl max-w-2xl w-full overflow-hidden flex flex-col pointer-events-auto"
      >
        {/* Header */}
        <div className="p-4 border-b border-white/10 flex items-center justify-between bg-black/20">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-sky-500/20 text-sky-400">
              <Video className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white tracking-tight">{webcam.title}</h3>
              <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                <MapPin className="w-3.5 h-3.5 text-red-400" />
                <span>{webcam.city}, {webcam.country}</span>
                <span>•</span>
                <span className="font-mono">{webcam.lat.toFixed(3)}°, {webcam.lon.toFixed(3)}°</span>
              </div>
            </div>
          </div>

          <button
            id="close-webcam-modal-btn"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Image Preview Container */}
        <div className="relative bg-black aspect-video flex items-center justify-center overflow-hidden">
          <img
            src={webcam.previewUrl}
            alt={webcam.title}
            className="w-full h-full object-cover"
            referrerPolicy="no-referrer"
          />

          {/* Live badge overlay */}
          <div className="absolute top-3 left-3 bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full border border-white/10 flex items-center gap-2 text-xs text-white">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="font-bold uppercase tracking-wider text-[10px]">LIVE OBSERVATION</span>
          </div>

          <div className="absolute bottom-3 right-3 bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-md border border-white/10 text-[11px] text-slate-300">
            Updated: {webcam.updatedAt}
          </div>
        </div>

        {/* Footer Details */}
        <div className="p-3.5 bg-black/20 border-t border-white/10 flex items-center justify-between text-xs text-slate-400">
          <span>Global Meteorological Observation Cameras</span>
          <button
            id="refresh-webcam-btn"
            onClick={() => {}}
            className="flex items-center gap-1.5 text-sky-400 hover:text-sky-300 transition-colors cursor-pointer font-medium"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Reload Stream</span>
          </button>
        </div>
      </div>
    </div>
  );
};
