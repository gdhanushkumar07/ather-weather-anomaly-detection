import { useEffect, useRef } from 'react';
import type React from 'react';
import type { Map as LeafletMap } from 'leaflet';
import type { WeatherLayerType } from '../../types/weather';
import {
  TEMP_COLOR_RAMP,
  RAIN_COLOR_RAMP,
  CLOUDS_COLOR_RAMP,
  WAVES_COLOR_RAMP,
  PRESSURE_COLOR_RAMP,
  HUMIDITY_COLOR_RAMP,
  THUNDER_COLOR_RAMP,
  interpolateColor,
} from '../../utils/colorScales';

interface HeatmapOverlayProps {
  map: LeafletMap | null;
  layer: WeatherLayerType;
  timeOffsetHours: number;
}

export const HeatmapOverlay: React.FC<HeatmapOverlayProps> = ({
  map,
  layer,
  timeOffsetHours,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const timeOffsetRef = useRef(timeOffsetHours);
  const layerRef = useRef(layer);
  const isRenderingRef = useRef(false);

  useEffect(() => {
    timeOffsetRef.current = timeOffsetHours;
    triggerRender();
  }, [timeOffsetHours]);

  useEffect(() => {
    layerRef.current = layer;
    triggerRender();
  }, [layer]);

  const triggerRender = () => {
    if (!map || isRenderingRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (layerRef.current === 'none' || layerRef.current === 'wind' || layerRef.current === 'anomalies') {
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    isRenderingRef.current = true;
    requestAnimationFrame(() => {
      renderHeatmap();
      isRenderingRef.current = false;
    });
  };

  const renderHeatmap = () => {
    if (!map) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const size = map.getSize();
    const width = size.x;
    const height = size.y;

    const scale = 8;
    const gridW = Math.ceil(width / scale);
    const gridH = Math.ceil(height / scale);

    if (canvas.width !== gridW || canvas.height !== gridH) {
      canvas.width = gridW;
      canvas.height = gridH;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }

    const currentLayer = layerRef.current;
    const currentOffset = timeOffsetRef.current;

    const imgData = ctx.createImageData(gridW, gridH);
    const data = imgData.data;

    const bounds = map.getBounds();
    const north = bounds.getNorth();
    const south = bounds.getSouth();
    const west = bounds.getWest();
    const east = bounds.getEast();

    for (let y = 0; y < gridH; y++) {
      const lat = north - (y / gridH) * (north - south);
      const radLat = (lat * Math.PI) / 180;

      for (let x = 0; x < gridW; x++) {
        const lon = west + (x / gridW) * (east - west);
        const radLon = (lon * Math.PI) / 180;
        const pixelIdx = (y * gridW + x) * 4;

        let r = 0, g = 0, b = 0, a = 0;

        if (currentLayer === 'temp') {
          const baseSolar = 32 * Math.cos(radLat) - Math.abs(lat) * 0.45;
          const landOceanDelta = Math.sin(radLon * 3) * 4;
          const diurnal = Math.sin((lon / 15 + currentOffset) * (Math.PI / 12)) * 5;
          const tempVal = baseSolar + landOceanDelta + diurnal;

          const colorStr = interpolateColor(TEMP_COLOR_RAMP, tempVal);
          const rgba = parseRgba(colorStr);
          r = rgba[0]; g = rgba[1]; b = rgba[2]; a = 140;
        } else if (currentLayer === 'rain' || currentLayer === 'radar') {
          const cycloneNoise = Math.sin(radLat * 6 + currentOffset * 0.2) * Math.cos(radLon * 5);
          const front = Math.sin(lat * 0.3 + lon * 0.3 + currentOffset * 0.15);
          const rainIntensity = Math.max(0, cycloneNoise * 18 + front * 10 - 4);

          if (rainIntensity > 0.5) {
            const colorStr = interpolateColor(RAIN_COLOR_RAMP, rainIntensity);
            const rgba = parseRgba(colorStr);
            r = rgba[0]; g = rgba[1]; b = rgba[2]; a = Math.min(220, Math.floor(rgba[3] * 230));
          }
        } else if (currentLayer === 'thunder') {
          const stormCenter1 = Math.exp(-((lat - 22) ** 2 + (lon - 84) ** 2) / 60);
          const stormCenter2 = Math.exp(-((lat - 15) ** 2 + (lon - 74) ** 2) / 45);
          const stormVal = Math.min(100, (stormCenter1 + stormCenter2) * 95 + Math.sin(currentOffset * 0.3) * 15);
          if (stormVal > 15) {
            const colorStr = interpolateColor(THUNDER_COLOR_RAMP, stormVal);
            const rgba = parseRgba(colorStr);
            r = rgba[0]; g = rgba[1]; b = rgba[2]; a = Math.min(220, Math.floor(rgba[3] * 220));
          }
        } else if (currentLayer === 'humidity') {
          const humField = 55 + Math.sin(radLat * 4 + currentOffset * 0.08) * 25 + Math.cos(radLon * 3) * 15;
          const colorStr = interpolateColor(HUMIDITY_COLOR_RAMP, Math.min(100, Math.max(10, humField)));
          const rgba = parseRgba(colorStr);
          r = rgba[0]; g = rgba[1]; b = rgba[2]; a = 135;
        } else if (currentLayer === 'clouds' || currentLayer === 'satellite') {
          const cloudField = Math.sin(radLat * 5 + currentOffset * 0.1) * Math.cos(radLon * 4 + radLat * 2);
          const cloudPct = Math.max(0, Math.min(100, (cloudField + 0.6) * 65));
          if (cloudPct > 15) {
            const colorStr = interpolateColor(CLOUDS_COLOR_RAMP, cloudPct);
            const rgba = parseRgba(colorStr);
            r = rgba[0]; g = rgba[1]; b = rgba[2]; a = Math.min(190, Math.floor(rgba[3] * 180));
          }
        } else if (currentLayer === 'waves') {
          const waveBase = Math.abs(Math.sin(radLat * 3)) * 4.5 + Math.sin(radLon * 4) * 1.5;
          const waveVal = Math.max(0.5, waveBase);
          const colorStr = interpolateColor(WAVES_COLOR_RAMP, waveVal);
          const rgba = parseRgba(colorStr);
          r = rgba[0]; g = rgba[1]; b = rgba[2]; a = 150;
        } else if (currentLayer === 'pressure') {
          const pVal = 1013 - (lat > 0 ? 15 : -15) * Math.sin(radLat * 2) + Math.sin(radLon * 3) * 18;
          // Isobar contour line effect (bands every 4 hPa)
          const isContour = Math.abs(pVal % 4) < 0.45;
          if (isContour) {
            r = 255; g = 255; b = 255; a = 190;
          } else {
            const colorStr = interpolateColor(PRESSURE_COLOR_RAMP, pVal);
            const rgba = parseRgba(colorStr);
            r = rgba[0]; g = rgba[1]; b = rgba[2]; a = 130;
          }
        }

        data[pixelIdx] = r;
        data[pixelIdx + 1] = g;
        data[pixelIdx + 2] = b;
        data[pixelIdx + 3] = a;
      }
    }

    ctx.putImageData(imgData, 0, 0);
  };

  function parseRgba(str: string): [number, number, number, number] {
    const match = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
    if (match) {
      return [
        parseInt(match[1], 10),
        parseInt(match[2], 10),
        parseInt(match[3], 10),
        match[4] !== undefined ? parseFloat(match[4]) : 1.0,
      ];
    }
    return [0, 0, 0, 0];
  }

  useEffect(() => {
    if (!map) return;

    triggerRender();
    map.on('moveend', triggerRender);
    map.on('zoomend', triggerRender);
    map.on('resize', triggerRender);

    return () => {
      map.off('moveend', triggerRender);
      map.off('zoomend', triggerRender);
      map.off('resize', triggerRender);
    };
  }, [map]);

  if (layer === 'none' || layer === 'wind' || layer === 'anomalies') return null;

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-[12] transition-opacity duration-300 opacity-90 filter blur-[2px]"
      style={{ imageRendering: 'auto' }}
    />
  );
};
