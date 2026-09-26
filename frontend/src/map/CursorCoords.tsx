import React, { useEffect, useRef } from 'react';
import type maplibregl from 'maplibre-gl';

interface CursorCoordsProps {
  map: maplibregl.Map | null;
}

const fmt = (n: number) => `${n.toFixed(2)}°`;

/**
 * Live LAT/LON readout that follows the cursor while it is over the globe/map.
 * Updates the DOM directly (no React state) so mouse-move stays cheap.
 */
export const CursorCoords: React.FC<CursorCoordsProps> = ({ map }) => {
  const boxRef = useRef<HTMLDivElement>(null);
  const latRef = useRef<HTMLDivElement>(null);
  const lonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!map || !box) return;

    const hide = () => { box.style.opacity = '0'; };

    const onMove = (e: maplibregl.MapMouseEvent) => {
      const ll = map.unproject(e.point);
      // Off the globe, unproject clamps to the horizon, so projecting the
      // result back lands somewhere other than the cursor.
      const back = map.project(ll);
      if (Math.hypot(back.x - e.point.x, back.y - e.point.y) > 3) return hide();

      if (latRef.current) latRef.current.textContent = `LAT: ${fmt(ll.lat)}`;
      if (lonRef.current) lonRef.current.textContent = `LON: ${fmt(ll.wrap().lng)}`;
      box.style.transform = `translate(${e.point.x + 18}px, ${e.point.y + 18}px)`;
      box.style.opacity = '1';
    };

    map.on('mousemove', onMove);
    map.on('mouseout', hide);
    map.on('dragstart', hide);
    return () => {
      map.off('mousemove', onMove);
      map.off('mouseout', hide);
      map.off('dragstart', hide);
    };
  }, [map]);

  return (
    <div ref={boxRef} className="cursor-coords" aria-hidden="true">
      <div ref={latRef} />
      <div ref={lonRef} />
    </div>
  );
};
