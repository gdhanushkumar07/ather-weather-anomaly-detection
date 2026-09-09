import { useEffect, useRef, useState, useCallback } from 'react';
import type React from 'react';
import { Play, Pause, RotateCcw } from 'lucide-react';
import type { ForecastModel } from '../../types/weather';

interface TimelineSliderProps {
  isPlaying: boolean;
  onTogglePlay: () => void;
  timeOffsetHours: number;
  onTimeChange: (hours: number) => void;
  selectedModel: ForecastModel;
  onSelectModel: (model: ForecastModel) => void;
}

export const TimelineSlider: React.FC<TimelineSliderProps> = ({
  isPlaying,
  onTogglePlay,
  timeOffsetHours,
  onTimeChange,
  selectedModel,
  onSelectModel,
}) => {
  const maxHours = 120;
  const [playSpeed, setPlaySpeed] = useState<number>(1);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const isDraggingRef = useRef<boolean>(false);

  const onTimeChangeRef = useRef(onTimeChange);
  useEffect(() => {
    onTimeChangeRef.current = onTimeChange;
  }, [onTimeChange]);

  const currentTimeRef = useRef(timeOffsetHours);
  useEffect(() => {
    currentTimeRef.current = timeOffsetHours;
  }, [timeOffsetHours]);

  useEffect(() => {
    if (!isPlaying) return;

    let animFrameId: number;
    let lastTimestamp = performance.now();
    let accumulatedTime = 0;
    const intervalDuration = playSpeed === 2 ? 500 : 950;

    const loop = (currentTimestamp: number) => {
      const delta = currentTimestamp - lastTimestamp;
      lastTimestamp = currentTimestamp;
      accumulatedTime += delta;

      if (accumulatedTime >= intervalDuration) {
        accumulatedTime -= intervalDuration;
        const nextTime = (currentTimeRef.current + 1) % maxHours;
        currentTimeRef.current = nextTime;
        onTimeChangeRef.current(nextTime);
      }
      animFrameId = requestAnimationFrame(loop);
    };

    animFrameId = requestAnimationFrame(loop);

    return () => cancelAnimationFrame(animFrameId);
  }, [isPlaying, playSpeed, maxHours]);

  const now = new Date();
  const currentDate = new Date(now.getTime() + timeOffsetHours * 60 * 60 * 1000);
  const formattedDay = currentDate.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  const formattedTime = currentDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

  const dayTicks = [];
  for (let h = 0; h <= maxHours; h += 24) {
    const d = new Date(now.getTime() + h * 60 * 60 * 1000);
    const isFirst = h === 0;
    dayTicks.push({
      hourOffset: h,
      label: isFirst ? 'Today' : d.toLocaleDateString([], { weekday: 'short' }),
      dateNumber: d.getDate(),
      pct: (h / maxHours) * 100,
    });
  }

  const updateTimeFromPointer = useCallback((clientX: number) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const targetHour = Math.round(pos * maxHours);
    onTimeChangeRef.current(targetHour);
  }, [maxHours]);

  const handlePointerDown = (e: React.PointerEvent) => {
    isDraggingRef.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    updateTimeFromPointer(e.clientX);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isDraggingRef.current) return;
    updateTimeFromPointer(e.clientX);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    isDraggingRef.current = false;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
  };

  const models: { id: ForecastModel; label: string; resolution: string }[] = [
    { id: 'ECMWF', label: 'ECMWF', resolution: '9km' },
    { id: 'GFS', label: 'GFS', resolution: '22km' },
    { id: 'ICON', label: 'ICON', resolution: '13km' },
  ];

  const currentPct = (timeOffsetHours / maxHours) * 100;

  return (
    <div className="absolute bottom-4 left-4 lg:left-[260px] right-4 xl:right-[340px] z-30 select-none transition-all duration-300">
      <div className="windy-glass rounded-2xl px-4 py-2.5 shadow-2xl flex flex-col gap-1.5 border border-white/10 backdrop-blur-md">
        
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              onClick={onTogglePlay}
              className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-cyan-500 hover:bg-cyan-400 text-slate-950 flex items-center justify-center shadow-lg shadow-cyan-500/30 transition-all active:scale-95"
            >
              {isPlaying ? (
                <Pause className="w-3.5 h-3.5 sm:w-4 sm:h-4 fill-current" />
              ) : (
                <Play className="w-3.5 h-3.5 sm:w-4 sm:h-4 fill-current ml-0.5" />
              )}
            </button>

            <button
              onClick={() => onTimeChange(0)}
              className="text-slate-400 hover:text-white p-1 rounded-md transition-colors"
              title="Reset to current time"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => setPlaySpeed(playSpeed === 1 ? 2 : 1)}
              className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 hover:bg-white/15 text-cyan-300 border border-white/10 transition-colors"
            >
              {playSpeed}x
            </button>

            <div className="flex items-baseline gap-1.5 text-xs font-semibold">
              <span className="text-white px-2 py-0.5 rounded-lg bg-white/10 border border-white/10">
                {formattedDay}
              </span>
              <span className="text-cyan-400 font-mono text-sm tracking-wide">
                {formattedTime}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-slate-400 hidden sm:inline uppercase font-bold tracking-wider">
              Model:
            </span>
            <div className="flex items-center bg-black/40 rounded-xl p-0.5 border border-white/10">
              {models.map((m) => (
                <button
                  key={m.id}
                  onClick={() => onSelectModel(m.id)}
                  className={`px-2 py-0.5 rounded-lg text-xs font-medium transition-all ${
                    selectedModel === m.id
                      ? 'bg-cyan-500/30 text-cyan-300 font-bold border border-cyan-400/30 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>{m.label}</span>
                  <span className="text-[9px] opacity-70 ml-1 hidden md:inline">{m.resolution}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

{/* Timeline Day Markers & Interactive Scrubber Track */}
        <div className="relative w-full pt-1 pb-1">
          {/* Day markers */}
          <div className="relative w-full h-3.5 text-[10px] text-slate-400 font-medium select-none">
            {dayTicks.map((dt, i) => {
              const isFirst = i === 0;
              const isLast = i === dayTicks.length - 1;
              
              return (
                <div
                  key={dt.hourOffset}
                  className={`absolute flex flex-col cursor-pointer hover:text-cyan-300 transition-colors ${
                    isFirst ? 'left-0 items-start' : isLast ? 'right-0 items-end' : 'transform -translate-x-1/2 items-center'
                  }`}
                  style={!isFirst && !isLast ? { left: `${dt.pct}%` } : {}}
                  onClick={() => onTimeChange(dt.hourOffset)}
                >
                  <span>{dt.label} {dt.dateNumber}</span>
                </div>
              );
            })}
          </div>

          {/* Scrubber Track Area (Now a proper sibling outside the text height wrapper) */}
          <div
            ref={trackRef}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            className="relative w-full h-5 flex items-center cursor-pointer touch-none group mt-1"
          >
            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden relative">
              <div
                className="h-full bg-gradient-to-r from-blue-600 via-cyan-500 to-cyan-400 transition-[width] duration-75"
                style={{ width: `${currentPct}%` }}
              />
            </div>
            <div
              className="absolute w-4 h-4 rounded-full bg-cyan-400 border-2 border-white shadow-[0_0_12px_rgba(34,211,238,0.8)] transform -translate-x-1/2 pointer-events-none transition-transform group-hover:scale-125"
              style={{ left: `${currentPct}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};