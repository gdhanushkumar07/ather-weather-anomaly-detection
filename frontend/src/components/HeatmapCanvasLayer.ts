import L from 'leaflet';
import { WeatherLayer } from '../types';
import {
  computeTemperature,
  computePrecipitation,
  computePressure,
  computeCloudCover,
  computeHumidity,
  computeCape,
  computeRadarDbz,
  lerpColor,
  TEMP_STOPS,
  RAIN_STOPS,
  RADAR_STOPS,
  HUMIDITY_STOPS,
  PRESSURE_STOPS,
  extractIsobarsAndExtrema,
} from '../utils/meteorology';
import { computeWindVector } from '../utils/windMath';

export class HeatmapCanvasLayer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private offscreenCanvas: HTMLCanvasElement;
  private offscreenCtx: CanvasRenderingContext2D;
  private map: L.Map;
  private activeLayer: WeatherLayer = 'none';
  private timeOffsetHours = 0;
  private altitudeLevel = 'surface';
  private showPressureIsolines = true;
  private width = 0;
  private height = 0;
  private isRendering = false;

  constructor(map: L.Map, canvas: HTMLCanvasElement) {
    this.map = map;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { willReadFrequently: false })!;
    this.offscreenCanvas = document.createElement('canvas');
    this.offscreenCtx = this.offscreenCanvas.getContext('2d', { willReadFrequently: true })!;
    this.resize();
  }

  public setLayer(layer: WeatherLayer) {
    this.activeLayer = layer;
    this.render();
  }

  public setShowPressureIsolines(show: boolean) {
    this.showPressureIsolines = show;
    if (this.activeLayer === 'pressure') {
      this.render();
    }
  }

  public setTimeOffset(hours: number) {
    this.timeOffsetHours = hours;
    this.render();
  }

  public setAltitudeLevel(alt: string) {
    this.altitudeLevel = alt;
    this.render();
  }

  public resize() {
    const size = this.map.getSize();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = size.x;
    this.height = size.y;
    this.canvas.width = Math.floor(this.width * dpr);
    this.canvas.height = Math.floor(this.height * dpr);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.scale(dpr, dpr);
    this.render();
  }

  public clear() {
    this.ctx.clearRect(0, 0, this.width, this.height);
  }

  public render() {
    // 1. Always completely wipe canvas first
    this.clear();

    // 2. If activeLayer is 'none', 'wind', or 'satellite', keep canvas completely clear
    // Satellite uses real satellite tile layer; Wind uses particle engine
    if (
      this.activeLayer === 'none' ||
      this.activeLayer === 'wind' ||
      this.activeLayer === 'satellite'
    ) {
      return;
    }

    if (this.width <= 0 || this.height <= 0) return;

    // 3. Optimized sampling grid (low-CPU, GPU bilinear-filtered)
    const gridW = Math.max(120, Math.min(Math.round(this.width / 4.5), 220));
    const gridH = Math.max(80, Math.min(Math.round(this.height / 4.5), 140));

    if (this.offscreenCanvas.width !== gridW || this.offscreenCanvas.height !== gridH) {
      this.offscreenCanvas.width = gridW;
      this.offscreenCanvas.height = gridH;
    }

    const imgData = this.offscreenCtx.createImageData(gridW, gridH);
    const data = imgData.data;

    // Buffer for pressure isobars extraction
    const isPressureLayer = this.activeLayer === 'pressure';
    const pressureGrid: number[][] = isPressureLayer ? [] : [];

    const stepX = this.width / gridW;
    const stepY = this.height / gridH;

    for (let gy = 0; gy < gridH; gy++) {
      const screenY = (gy + 0.5) * stepY;
      const rowPressure: number[] = isPressureLayer ? [] : [];

      for (let gx = 0; gx < gridW; gx++) {
        const screenX = (gx + 0.5) * stepX;
        const latLng = this.map.containerPointToLatLng(L.point(screenX, screenY));

        const rgba = this.evaluatePoint(latLng.lat, latLng.lng, this.activeLayer, this.timeOffsetHours);
        const idx = (gy * gridW + gx) * 4;
        data[idx] = rgba[0];
        data[idx + 1] = rgba[1];
        data[idx + 2] = rgba[2];
        data[idx + 3] = rgba[3];

        if (isPressureLayer) {
          rowPressure.push(computePressure(latLng.lat, latLng.lng, this.timeOffsetHours));
        }
      }

      if (isPressureLayer) {
        pressureGrid.push(rowPressure);
      }
    }

    this.offscreenCtx.putImageData(imgData, 0, 0);

    // 4. Smoothly upscale to main canvas using hardware bilinear interpolation
    this.ctx.save();
    this.ctx.imageSmoothingEnabled = true;
    this.ctx.imageSmoothingQuality = 'high';
    this.ctx.drawImage(this.offscreenCanvas, 0, 0, gridW, gridH, 0, 0, this.width, this.height);
    this.ctx.restore();

    // 5. If pressure layer, draw true data-driven isobars and H/L pressure centers via Marching Squares
    if (isPressureLayer && this.showPressureIsolines && pressureGrid.length > 0) {
      this.drawMarchingIsobars(pressureGrid, gridW, gridH, stepX, stepY);
    }
  }

  // --- Point Evaluation (Piecewise-Linear Continuous Interpolation) ---

  private evaluatePoint(lat: number, lon: number, layer: WeatherLayer, timeH: number): [number, number, number, number] {
    switch (layer) {
      case 'rain':
      case 'rain_accum': {
        const rainMm = computePrecipitation(lat, lon, timeH) * (layer === 'rain_accum' ? 3.0 : 1.0);
        return lerpColor(rainMm, RAIN_STOPS);
      }

      case 'temperature': {
        const tempC = computeTemperature(lat, lon, timeH, this.altitudeLevel);
        return lerpColor(tempC, TEMP_STOPS);
      }

      case 'pressure': {
        const p = computePressure(lat, lon, timeH);
        return lerpColor(p, PRESSURE_STOPS);
      }

      case 'radar': {
        const dbz = computeRadarDbz(lat, lon, timeH);
        return lerpColor(dbz, RADAR_STOPS);
      }

      case 'clouds': {
        const cloudCover = computeCloudCover(lat, lon, timeH);
        if (cloudCover < 14) return [0, 0, 0, 0]; // Crystal clear sky over deserts & high pressure
        // Soft continuous white/slate cloud opacity
        const alpha = Math.min(0.75, Math.pow((cloudCover - 14) / 86, 1.1) * 0.75);
        return [240, 245, 255, Math.round(alpha * 255)];
      }

      case 'humidity': {
        const hum = computeHumidity(lat, lon, timeH);
        return lerpColor(hum, HUMIDITY_STOPS);
      }

      case 'thunderstorms': {
        const cape = computeCape(lat, lon, timeH);
        if (cape < 450) return [0, 0, 0, 0];
        const alpha = Math.min(0.85, (cape / 3200) * 0.85);
        if (cape < 1200) return [234, 179, 8, Math.round(alpha * 255)];
        if (cape < 2400) return [249, 115, 22, Math.round(alpha * 255)];
        return [217, 70, 239, Math.round(alpha * 255)];
      }

      case 'gusts': {
        const vec = computeWindVector(lat, lon, timeH, this.altitudeLevel);
        const gustKnots = vec.speedKnots * 1.35 + 6;
        if (gustKnots < 12) return [0, 0, 0, 0];
        const alpha = Math.min(0.70, (gustKnots / 75) * 0.70);
        if (gustKnots < 25) return [56, 189, 248, Math.round(alpha * 255)];
        if (gustKnots < 45) return [34, 197, 94, Math.round(alpha * 255)];
        if (gustKnots < 65) return [249, 115, 22, Math.round(alpha * 255)];
        return [239, 68, 68, Math.round(alpha * 255)];
      }

      case 'waves': {
        const vec = computeWindVector(lat, lon, timeH, this.altitudeLevel);
        const waveHeightM = Math.max(0, (vec.speedKnots - 8) * 0.12);
        if (waveHeightM < 0.5) return [0, 0, 0, 0];
        const alpha = Math.min(0.72, (waveHeightM / 8.0) * 0.72);
        if (waveHeightM < 2.0) return [14, 165, 233, Math.round(alpha * 255)];
        if (waveHeightM < 4.0) return [13, 148, 136, Math.round(alpha * 255)];
        if (waveHeightM < 7.0) return [234, 179, 8, Math.round(alpha * 255)];
        return [239, 68, 68, Math.round(alpha * 255)];
      }

      default:
        return [0, 0, 0, 0];
    }
  }

  // --- 6. Authentic Marching Squares Isobars (Data-Driven Pressure Contours) ---

  private drawMarchingIsobars(
    grid: number[][],
    gridW: number,
    gridH: number,
    stepX: number,
    stepY: number
  ) {
    const { segments, extrema } = extractIsobarsAndExtrema(grid, gridW, gridH, stepX, stepY, 4);

    this.ctx.save();
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.72)';
    this.ctx.lineWidth = 1.3;
    this.ctx.beginPath();

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      this.ctx.moveTo(seg.x1, seg.y1);
      this.ctx.lineTo(seg.x2, seg.y2);
    }
    this.ctx.stroke();

    // Print isobar numerical labels along selected contours
    this.ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
    this.ctx.font = 'bold 10px monospace';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'middle';

    const labeledIsobars = new Set<number>();
    for (let i = 0; i < segments.length; i += 18) {
      const seg = segments[i];
      if (!labeledIsobars.has(seg.val) || i % 60 === 0) {
        labeledIsobars.add(seg.val);
        const midX = (seg.x1 + seg.x2) / 2;
        const midY = (seg.y1 + seg.y2) / 2;
        if (midX > 25 && midX < this.width - 25 && midY > 25 && midY < this.height - 25) {
          // Pill background for label readability
          this.ctx.fillStyle = 'rgba(15, 23, 42, 0.75)';
          this.ctx.fillRect(midX - 16, midY - 6, 32, 12);
          this.ctx.fillStyle = '#ffffff';
          this.ctx.fillText(`${seg.val}`, midX, midY);
        }
      }
    }

    // Draw authentic Synoptic 'H' (High) and 'L' (Low) centers derived from local extrema
    for (let i = 0; i < extrema.length; i++) {
      const ex = extrema[i];
      if (ex.x < 30 || ex.x > this.width - 30 || ex.y < 30 || ex.y > this.height - 30) continue;

      const isLow = ex.type === 'L';
      const bgColor = isLow ? '#dc2626' : '#2563eb';

      // Badge circle
      this.ctx.beginPath();
      this.ctx.arc(ex.x, ex.y, 14, 0, Math.PI * 2);
      this.ctx.fillStyle = bgColor;
      this.ctx.fill();
      this.ctx.strokeStyle = '#ffffff';
      this.ctx.lineWidth = 2.0;
      this.ctx.stroke();

      // Letter 'H' or 'L'
      this.ctx.fillStyle = '#ffffff';
      this.ctx.font = 'bold 13px sans-serif';
      this.ctx.textAlign = 'center';
      this.ctx.textBaseline = 'middle';
      this.ctx.fillText(ex.type, ex.x, ex.y);

      // Central pressure text underneath
      this.ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      this.ctx.fillRect(ex.x - 26, ex.y + 16, 52, 14);
      this.ctx.fillStyle = '#ffffff';
      this.ctx.font = 'bold 10px monospace';
      this.ctx.fillText(`${ex.value} hPa`, ex.x, ex.y + 23);
    }

    this.ctx.restore();
  }
}
