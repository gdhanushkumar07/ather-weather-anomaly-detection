import type React from 'react';
import { X, Camera, MapPin, ExternalLink } from 'lucide-react';
import type { WebcamItem } from '../../types/weather';

interface WebcamModalProps {
  webcam: WebcamItem | null;
  onClose: () => void;
}

export const WebcamModal: React.FC<WebcamModalProps> = ({ webcam, onClose }) => {
  if (!webcam) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in">
      <div className="windy-glass rounded-3xl max-w-2xl w-full border border-white/10 overflow-hidden shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-blue-500/20 border border-blue-400/30 flex items-center justify-center text-blue-400">
              <Camera className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">{webcam.title}</h3>
              <div className="text-xs text-slate-400 flex items-center gap-1">
                <MapPin className="w-3 h-3 text-cyan-400" />
                <span>{webcam.city}</span>
                <span>• Updated {webcam.updateTime}</span>
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 text-slate-300 hover:text-white flex items-center justify-center transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Live Camera Stream Feed */}
        <div className="relative aspect-video bg-black/80 flex items-center justify-center overflow-hidden">
          <img
            src={webcam.thumbnail}
            alt={webcam.title}
            className="w-full h-full object-cover"
          />
          <div className="absolute top-3 left-3 px-2.5 py-1 rounded-lg bg-red-600/80 backdrop-blur-sm text-white text-[11px] font-bold flex items-center gap-1.5 shadow-lg border border-red-500/40">
            <span className="w-2 h-2 rounded-full bg-white animate-ping" />
            LIVE FEED
          </div>
          <div className="absolute bottom-3 right-3 px-2.5 py-1 rounded-lg bg-black/60 backdrop-blur-sm text-slate-300 text-[11px] font-mono border border-white/10">
            FPS: 24 • 1080p
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-3 bg-black/20 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
            <span>High-definition optical telemetry online</span>
          </div>
          <button
            onClick={() => window.open(webcam.thumbnail, '_blank')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white font-medium transition-colors"
          >
            <span>Full Resolution</span>
            <ExternalLink className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
};
