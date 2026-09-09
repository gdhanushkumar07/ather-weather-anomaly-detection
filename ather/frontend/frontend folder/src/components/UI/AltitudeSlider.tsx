import type React from 'react';
import type { AltitudeLevel } from '../../types/weather';

interface AltitudeSliderProps {
  altitude: AltitudeLevel;
  onSelectAltitude: (alt: AltitudeLevel) => void;
}

export const AltitudeSlider: React.FC<AltitudeSliderProps> = ({
  altitude,
  onSelectAltitude,
}) => {
  const levels: { id: AltitudeLevel; label: string; desc: string }[] = [
    { id: '300hpa', label: '300 hPa', desc: '9,000m (Jet)' },
    { id: '500hpa', label: '500 hPa', desc: '5,500m' },
    { id: '700hpa', label: '700 hPa', desc: '3,000m' },
    { id: '850hpa', label: '850 hPa', desc: '1,500m' },
    { id: '100m', label: '100 m', desc: 'Boundary' },
    { id: 'surface', label: 'Surface', desc: 'Ground 10m' },
  ];

  return (
    <div className="absolute right-3 bottom-24 z-30 hidden md:flex flex-col items-center">
      <div className="windy-glass rounded-2xl p-1.5 shadow-2xl flex flex-col gap-1 border border-white/10">
        <div className="text-[9px] uppercase font-bold text-slate-400 px-1.5 py-0.5 text-center tracking-wider">
          Altitude
        </div>
        {levels.map((lvl) => {
          const isActive = altitude === lvl.id;
          return (
            <button
              key={lvl.id}
              onClick={() => onSelectAltitude(lvl.id)}
              className={`px-2 py-1.5 rounded-lg text-[11px] transition-all flex flex-col items-center text-center ${
                isActive
                  ? 'bg-cyan-500/30 text-cyan-300 font-bold border border-cyan-400/40 shadow-sm'
                  : 'text-slate-300 hover:bg-white/10 hover:text-white'
              }`}
              title={lvl.desc}
            >
              <span>{lvl.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
