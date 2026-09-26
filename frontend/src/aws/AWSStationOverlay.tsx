import React, { useEffect, useRef, useState, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import maplibregl from 'maplibre-gl';
import { AWSModel, awsStatusColor } from './AWSModel';
import { AWSErrorBoundary } from './AWSErrorBoundary';

const OVERLAY_WIDTH = 180;
const OVERLAY_HEIGHT = 220;

interface AWSStationOverlayProps {
  map: maplibregl.Map;
  stationId: string;
  stationName: string;
  lng: number;
  lat: number;
  status: string;
}

/**
 * Renders exactly one interactive 3D AWS model, for the currently-selected
 * station only. Position is re-projected from real lat/lng via MapLibre's
 * own `map.project()` on every 'move'/'zoom'/'rotate'/'pitch' event -- the
 * same coordinate system the map itself uses, not a second conversion
 * system -- so the model tracks pan/zoom/globe-rotation exactly like a
 * native map marker would. Position updates go straight to a DOM
 * transform via a ref (not React state) to avoid re-rendering the R3F
 * canvas on every map frame.
 *
 * OrbitControls is scoped to this small canvas's own hitbox only. Because
 * this is a separate DOM element sitting on top of (not inside) MapLibre's
 * canvas, pointer events here never reach MapLibre's handlers -- dragging
 * the model can't pan/rotate the underlying map.
 */
export const AWSStationOverlay: React.FC<AWSStationOverlayProps> = ({
  map,
  stationId,
  stationName,
  lng,
  lat,
  status,
}) => {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);
  // Fades/scales the overlay in on mount rather than popping in abruptly --
  // the "dot grows into an AWS" transition. False on the very first paint,
  // flipped true a frame later so the CSS transition actually runs.
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const updatePosition = () => {
      const el = wrapperRef.current;
      if (!el) return;
      const point = map.project([lng, lat]);
      el.style.transform = `translate(${point.x - OVERLAY_WIDTH / 2}px, ${point.y - OVERLAY_HEIGHT}px)`;
    };

    updatePosition();
    map.on('move', updatePosition);
    map.on('zoom', updatePosition);
    map.on('rotate', updatePosition);
    map.on('pitch', updatePosition);
    return () => {
      map.off('move', updatePosition);
      map.off('zoom', updatePosition);
      map.off('rotate', updatePosition);
      map.off('pitch', updatePosition);
    };
  }, [map, lng, lat]);

  return (
    <div
      ref={wrapperRef}
      className="aws-station-overlay"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: OVERLAY_WIDTH,
        height: OVERLAY_HEIGHT,
        pointerEvents: 'none',
        willChange: 'transform',
      }}
    >
      <div
        className="aws-overlay-enter"
        style={{
          width: '100%',
          height: '100%',
          opacity: entered ? 1 : 0,
          transform: `scale(${entered ? 1 : 0.6})`,
          transformOrigin: 'center bottom',
          transition: 'opacity 320ms ease, transform 320ms cubic-bezier(0.34, 1.4, 0.64, 1)',
        }}
      >
        {hovered && (
          <div className="aws-hover-tooltip">
            <div className="aws-tooltip-id">{stationId}</div>
            <div className="aws-tooltip-loc">{stationName}</div>
            <div className={`aws-tooltip-status status-${status}`}>Status: {status}</div>
          </div>
        )}

        <div
          className="aws-canvas-hitbox"
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            width: '100%',
            height: '85%',
            pointerEvents: 'auto',
            cursor: 'pointer',
          }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          <AWSErrorBoundary
            fallback={
              <div className="aws-model-fallback-dot" style={{ background: awsStatusColor(status) }} />
            }
          >
            <Canvas camera={{ position: [1.6, 1.4, 2.2], fov: 40 }} gl={{ alpha: true, antialias: true }}>
              <ambientLight intensity={0.9} />
              <directionalLight position={[3, 4, 2]} intensity={1.1} />
              <directionalLight position={[-2, 1, -2]} intensity={0.3} />
              <Suspense fallback={null}>
                <group scale={hovered ? 1.08 : 1}>
                  <AWSModel status={status} selected />
                </group>
              </Suspense>
              <OrbitControls
                makeDefault
                enablePan={false}
                enableZoom={false}
                enableDamping
                dampingFactor={0.12}
                minPolarAngle={Math.PI / 6}
                maxPolarAngle={Math.PI / 1.9}
                target={[0, 1.1, 0]}
              />
            </Canvas>
          </AWSErrorBoundary>
        </div>
      </div>
    </div>
  );
};
