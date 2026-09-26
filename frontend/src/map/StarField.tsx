import React, { useEffect, useRef } from 'react';
import type maplibregl from 'maplibre-gl';
import starsUrl from '../../assets/starstwo.png';

// How many screen pixels the star field slides per degree of globe rotation.
// Distant stars should drift slower than the near Earth, so this is kept
// well below the globe's own surface speed.
const PX_PER_DEGREE = 6;

// starstwo.png is a small (525x350) photo. 1 keeps its stars crisp; raise it
// to spread the (mirrored) repeat further apart at the cost of sharpness.
const TILE_SCALE = 1;

interface StarFieldProps {
  map: maplibregl.Map | null;
}

/**
 * Deep-space backdrop rendered behind the (transparent-outside-the-globe)
 * MapLibre canvas. The star photo is tiled (mirrored, so edges are seamless) and
 * offset/rotated from the map camera, so the sky moves with the globe as it is dragged, zoomed or rotated.
 */
export const StarField: React.FC<StarFieldProps> = ({ map }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let disposed = false;
    let pattern: CanvasPattern | null = null;
    let raf = 0;
    let dpr = 1;

    const draw = () => {
      raf = 0;
      if (disposed || !pattern) return;
      const w = canvas.width;
      const h = canvas.height;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, w, h);

      const center = map?.getCenter();
      const lng = center?.lng ?? 0;
      const lat = center?.lat ?? 0;
      const bearing = map?.getBearing() ?? 0;
      // Zooming in pushes the sky back slightly (mild parallax).
      const zoom = map?.getZoom() ?? 2;
      const scale = 1 + Math.max(0, zoom - 2) * 0.03;

      // Dragging the globe east moves the surface left; the sky follows the
      // same direction, just slower.
      const ox = -lng * PX_PER_DEGREE;
      const oy = lat * PX_PER_DEGREE;

      ctx.translate(w / 2, h / 2);
      ctx.rotate((-bearing * Math.PI) / 180);
      ctx.scale(scale * dpr, scale * dpr);
      ctx.translate(ox, oy);
      ctx.scale(TILE_SCALE, TILE_SCALE);
      ctx.fillStyle = pattern;
      // Cover the whole canvas even after rotation/offset (pattern is
      // anchored in this transformed space, so it moves with the camera).
      const r = Math.hypot(w, h) / (scale * dpr * TILE_SCALE);
      ctx.fillRect(-ox / TILE_SCALE - r, -oy / TILE_SCALE - r, 2 * r, 2 * r);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(draw);
    };

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      schedule();
    };

    const img = new Image();
    img.onload = () => {
      if (disposed) return;
      // Mirrored 2x2 tile => no visible seams when repeated.
      const tile = document.createElement('canvas');
      tile.width = img.naturalWidth * 2;
      tile.height = img.naturalHeight * 2;
      const t = tile.getContext('2d')!;
      for (let ix = 0; ix < 2; ix++) {
        for (let iy = 0; iy < 2; iy++) {
          t.save();
          t.translate(ix ? tile.width : 0, iy ? tile.height : 0);
          t.scale(ix ? -1 : 1, iy ? -1 : 1);
          t.drawImage(img, 0, 0);
          t.restore();
        }
      }
      pattern = ctx.createPattern(tile, 'repeat');
      schedule();
    };
    img.src = starsUrl;

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    map?.on('move', schedule);
    map?.on('resize', resize);

    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      map?.off('move', schedule);
      map?.off('resize', resize);
    };
  }, [map]);

  return <canvas ref={canvasRef} className="star-field" aria-hidden="true" />;
};
