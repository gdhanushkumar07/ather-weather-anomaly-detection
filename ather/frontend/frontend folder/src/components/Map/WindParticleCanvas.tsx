import { useEffect, useRef } from 'react';
import type React from 'react';
import type { Map as LeafletMap } from 'leaflet';
import { WIND_COLOR_RAMP, interpolateColor } from '../../utils/colorScales';
import type { AltitudeLevel } from '../../types/weather';

interface WindParticleCanvasProps {
  map: LeafletMap | null;
  isPlaying: boolean;
  timeOffsetHours: number;
  altitude: AltitudeLevel;
  particleDensity?: number;
  speedMultiplier?: number;
  visible: boolean;
}

interface Particle {
  x: number;
  y: number;
  age: number;
  maxLife: number;
}

export const WindParticleCanvas: React.FC<WindParticleCanvasProps> = ({
  map,
  isPlaying,
  timeOffsetHours,
  altitude,
  particleDensity = 1.0,
  speedMultiplier = 1.0,
  visible,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameIdRef = useRef<number | null>(null);
  const particlesRef = useRef<Particle[]>([]);

  // State refs to keep animation continuous without teardown
  const isPlayingRef = useRef(isPlaying);
  const timeOffsetRef = useRef(timeOffsetHours);
  const altitudeRef = useRef(altitude);
  const speedRef = useRef(speedMultiplier);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    timeOffsetRef.current = timeOffsetHours;
  }, [timeOffsetHours]);

  useEffect(() => {
    altitudeRef.current = altitude;
  }, [altitude]);

  useEffect(() => {
    speedRef.current = speedMultiplier;
  }, [speedMultiplier]);

  useEffect(() => {
    if (!map || !visible) {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { willReadFrequently: false });
    if (!ctx) return;

    function resizeCanvas() {
      if (!map || !canvas) return;
      const size = map.getSize();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = size.x * dpr;
      canvas.height = size.y * dpr;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
      ctx!.scale(dpr, dpr);
      initParticles();
    }

    function initParticles() {
      if (!map) return;
      const size = map.getSize();
      const baseCount = Math.floor(Math.min(size.x * size.y * 0.007, 9000) * particleDensity);
      const newParticles: Particle[] = [];
      for (let i = 0; i < baseCount; i++) {
        newParticles.push({
          x: Math.random() * size.x,
          y: Math.random() * size.y,
          age: Math.floor(Math.random() * 60),
          maxLife: 40 + Math.floor(Math.random() * 50),
        });
      }
      particlesRef.current = newParticles;
    }

    resizeCanvas();
    map.on('resize', resizeCanvas);
    map.on('move', () => {
      const size = map.getSize();
      particlesRef.current.forEach((p, idx) => {
        if (idx % 4 === 0) {
          p.x = Math.random() * size.x;
          p.y = Math.random() * size.y;
          p.age = 0;
        }
      });
    });

    const altFactorMap: Record<AltitudeLevel, number> = {
      surface: 1.0,
      '100m': 1.25,
      '850hpa': 1.6,
      '700hpa': 2.1,
      '500hpa': 2.8,
      '300hpa': 3.8,
    };

    function getWindVector(lat: number, lon: number, tOffset: number, alt: AltitudeLevel) {
      const radLat = (lat * Math.PI) / 180;
      const radLon = ((lon + tOffset * 1.5) * Math.PI) / 180;
      const altMultiplier = altFactorMap[alt] || 1.0;

      let u = 0;
      let v = 0;

      if (lat > 60) {
        u = -12 * Math.cos(radLat);
        v = -3 * Math.sin(radLon * 2);
      } else if (lat > 30) {
        u = (22 + 10 * Math.sin(radLon * 3)) * Math.cos(radLat);
        v = 8 * Math.sin(radLon * 4 + radLat);
      } else if (lat > -5) {
        const monsoonSwell = Math.sin(radLon * 2);
        u = -14 + 6 * monsoonSwell;
        v = -6 + 10 * Math.cos(radLon * 2.5);
      } else if (lat > -30) {
        u = -16 * Math.cos(radLat);
        v = 5 * Math.sin(radLon * 2);
      } else {
        u = 28 * Math.cos(radLat);
        v = 4 * Math.sin(radLon * 3);
      }

      // Cyclone simulation centered in Bay of Bengal & Arabian Sea
      const cyclone1Lat = 16.5 + 2 * Math.sin(tOffset * 0.08);
      const cyclone1Lon = 88.0 + 3 * Math.cos(tOffset * 0.08);
      const dLat1 = lat - cyclone1Lat;
      const dLon1 = lon - cyclone1Lon;
      const dist1Sq = dLat1 * dLat1 + dLon1 * dLon1;
      if (dist1Sq < 400) {
        const dist = Math.sqrt(dist1Sq) + 0.5;
        const speed = (280 / (dist + 4)) * Math.exp(-dist / 14);
        u += (dLat1 / dist) * speed;
        v += (-dLon1 / dist) * speed * 0.8;
      }

      const noise = Math.sin(radLat * 8 + radLon * 8 + tOffset * 0.1) * 3;
      u += noise;
      v += noise * 0.7;

      const totalSpeed = Math.sqrt(u * u + v * v) * altMultiplier;
      return { u, v, speed: totalSpeed };
    }

    function renderLoop() {
      if (!map || !canvas) return;

      const size = map.getSize();
      const width = size.x;
      const height = size.y;

      ctx!.save();
      ctx!.globalCompositeOperation = 'destination-out';
      ctx!.fillStyle = 'rgba(0, 0, 0, 0.12)';
      ctx!.fillRect(0, 0, width, height);
      ctx!.restore();

      ctx!.lineWidth = 1.4;
      ctx!.lineCap = 'round';

      const particles = particlesRef.current;
      const len = particles.length;
      const currentOffset = timeOffsetRef.current;
      const currentAlt = altitudeRef.current;
      const currentSpeed = speedRef.current;
      const altMult = altFactorMap[currentAlt] || 1.0;
      const activePlay = isPlayingRef.current;

      for (let i = 0; i < len; i++) {
        const p = particles[i];

        if (p.age > p.maxLife || p.x < -10 || p.x > width + 10 || p.y < -10 || p.y > height + 10) {
          p.x = Math.random() * width;
          p.y = Math.random() * height;
          p.age = 0;
          p.maxLife = 35 + Math.floor(Math.random() * 45);
          continue;
        }

        const latLng = map.containerPointToLatLng([p.x, p.y]);
        const wind = getWindVector(latLng.lat, latLng.lng, currentOffset, currentAlt);

        const nextLatLng = {
          lat: latLng.lat + (wind.v * 0.008 * currentSpeed * altMult),
          lng: latLng.lng + (wind.u * 0.008 * currentSpeed * altMult),
        };
        const nextPoint = map.latLngToContainerPoint(nextLatLng);

        const dx = nextPoint.x - p.x;
        const dy = nextPoint.y - p.y;

        const strokeColor = interpolateColor(WIND_COLOR_RAMP, wind.speed);
        ctx!.strokeStyle = strokeColor;
        ctx!.beginPath();
        ctx!.moveTo(p.x, p.y);
        ctx!.lineTo(p.x + dx, p.y + dy);
        ctx!.stroke();

        if (activePlay) {
          p.x += dx;
          p.y += dy;
          p.age += 1;
        } else {
          // Slow subtle drift even when paused so streamlines remain vibrant
          p.x += dx * 0.2;
          p.y += dy * 0.2;
        }
      }

      animFrameIdRef.current = requestAnimationFrame(renderLoop);
    }

    animFrameIdRef.current = requestAnimationFrame(renderLoop);

    return () => {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
      map.off('resize', resizeCanvas);
    };
  }, [map, visible, particleDensity]);

  return (
    <canvas
      ref={canvasRef}
      className={`absolute inset-0 pointer-events-none z-[15] transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
    />
  );
};
