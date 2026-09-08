import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, Trophy } from 'lucide-react';

interface TimelineSliderProps {
  currentHourOffset: number; // 0 to 240+ hours
  onChangeHourOffset: (hours: number) => void;
}

export const TimelineSlider: React.FC<TimelineSliderProps> = ({
  currentHourOffset,
  onChangeHourOffset,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const totalHours = 240; // 10 days of forecast (or up to 16 days)
  const stepHours = 3;

  // Auto-play interval
  useEffect(() => {
    let interval: any = null;
    if (isPlaying) {
      interval = setInterval(() => {
        onChangeHourOffset((prev: number) => {
          const next = prev + stepHours;
          if (next > totalHours) {
            return 0; // loop back to Now
          }
          return next;
        });
      }, 1000);
    } else if (!isPlaying && interval) {
      clearInterval(interval);
    }
    return () => clearInterval(interval);
  }, [isPlaying, onChangeHourOffset]);

  // Generate 16 forecast days
  const baseDate = new Date();
  const days: { label: string; startHour: number }[] = [];
  for (let d = 0; d < 16; d++) {
    const dObj = new Date(baseDate.getTime() + d * 24 * 3600 * 1000);
    const dayName = dObj.toLocaleDateString('en-US', { weekday: 'short' });
    const dayNum = dObj.getDate();
    days.push({
      label: `${dayName} ${dayNum}`,
      startHour: d * 24,
    });
  }

  // Calculate current selected hour time label (e.g. "8 PM")
  const selectedDate = new Date(baseDate.getTime() + currentHourOffset * 3600 * 1000);
  const hourVal = selectedDate.getHours();
  const hour12 = hourVal % 12 === 0 ? 12 : hourVal % 12;
  const ampm = hourVal >= 12 ? 'PM' : 'AM';
  const badgeTimeStr = currentHourOffset === 0 ? 'Now' : `${hour12} ${ampm}`;

  // Percentage position of playhead
  const progressPercent = Math.min(100, Math.max(0, (currentHourOffset / totalHours) * 100));

  return (
    <footer className="fixed bottom-0 left-0 right-0 z-[1000] w-full bg-[#131720]/90 backdrop-blur-xl border-t border-white/10 shadow-2xl pointer-events-auto select-none">
      <div className="flex items-center h-13 px-3 sm:px-4 gap-3 max-w-full overflow-hidden">
        {/* Play / Pause Circular Button */}
        <button
          id="timeline-play-btn"
          onClick={() => setIsPlaying(!isPlaying)}
          className="w-8 h-8 rounded-full bg-white hover:bg-slate-100 flex items-center justify-center shrink-0 shadow-lg cursor-pointer transition-transform active:scale-95"
          title={isPlaying ? 'Pause' : 'Play animation'}
        >
          {isPlaying ? (
            <Pause className="w-3.5 h-3.5 text-[#e5283c] fill-[#e5283c]" />
          ) : (
            <Play className="w-3.5 h-3.5 text-[#e5283c] fill-[#e5283c] ml-0.5" />
          )}
        </button>

        {/* Scrubber Area + Days Grid */}
        <div className="flex-1 flex flex-col justify-center relative h-full min-w-0">
          {/* Floating Time Badge on Playhead (e.g. "8 PM") */}
          <div
            className="absolute top-0.5 -translate-x-1/2 z-20 pointer-events-none transition-all duration-150"
            style={{ left: `${progressPercent}%` }}
          >
            <div className="bg-amber-500 text-slate-950 font-black text-[10px] px-2 py-0.5 rounded-full shadow-lg whitespace-nowrap">
              {badgeTimeStr}
            </div>
          </div>

          {/* Time Scrubber Track */}
          <div className="relative w-full h-1.5 bg-slate-700/60 rounded-full mt-3 overflow-hidden cursor-pointer">
            <div
              className="h-full bg-sky-400 rounded-full transition-all duration-150"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          {/* Invisible interactive range input overlaid on track */}
          <input
            id="timeline-slider-input"
            type="range"
            min="0"
            max={totalHours}
            step={stepHours}
            value={currentHourOffset}
            onChange={(e) => onChangeHourOffset(parseInt(e.target.value, 10))}
            className="absolute top-2.5 left-0 w-full h-4 opacity-0 cursor-pointer z-30"
          />

          {/* 16 Days Grid Row */}
          <div className="flex items-center justify-between gap-1 text-center mt-1 w-full overflow-x-auto no-scrollbar">
            {days.map((day, idx) => {
              const isCurrentDay = currentHourOffset >= day.startHour && currentHourOffset < day.startHour + 24;
              return (
                <button
                  key={idx}
                  id={`timeline-day-btn-${idx}`}
                  onClick={() => onChangeHourOffset(day.startHour)}
                  className={`flex items-center justify-center gap-0.5 py-0.5 text-[10px] font-medium transition-colors cursor-pointer shrink-0 px-1 ${
                    isCurrentDay
                      ? 'text-white font-bold border-b-2 border-amber-400'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span className="whitespace-nowrap">{day.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </footer>
  );
};
