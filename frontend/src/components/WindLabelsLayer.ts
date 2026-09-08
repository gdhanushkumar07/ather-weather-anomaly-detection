import L from 'leaflet';
import { computeWindVector } from '../utils/windMath';
import { WindSpeedUnit, TempUnit, WeatherLayer } from '../types';

export class WindLabelsLayer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private map: L.Map;
  private mode: WeatherLayer = 'none';
  private timeOffsetHours = 0;
  private altitudeLevel = 'surface';
  private windUnit: WindSpeedUnit = 'kt';
  private tempUnit: TempUnit = 'c';
  private width = 0;
  private height = 0;

  constructor(map: L.Map, canvas: HTMLCanvasElement) {
    this.map = map;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { willReadFrequently: false })!;
    this.resize();
  }

  public setMode(mode: WeatherLayer) {
    this.mode = mode;
    this.render();
  }

  public setTimeOffset(hours: number) {
    this.timeOffsetHours = hours;
    this.render();
  }

  public setAltitudeLevel(alt: string) {
    this.altitudeLevel = alt;
    this.render();
  }

  public setWindUnit(unit: WindSpeedUnit) {
    this.windUnit = unit;
    if (this.mode === 'wind') this.render();
  }

  public setTempUnit(unit: TempUnit) {
    this.tempUnit = unit;
    if (this.mode === 'temperature') this.render();
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
    this.ctx.scale(dpr, dpr);
    this.render();
  }

  public clear() {
    this.ctx.clearRect(0, 0, this.width, this.height);
  }

  public render() {
    // Keep canvas 100% clean - do not draw repeated rectangular badges or thousands of static arrows across the map
    this.clear();
  }

  private drawGenericPill(x: number, y: number, text: string, bgColor: string) {
    this.ctx.font = 'bold 10px system-ui, -apple-system, sans-serif';
    const textMetrics = this.ctx.measureText(text);
    const textW = textMetrics.width;
    const totalW = textW + 12;
    const totalH = 17;
    const boxX = x - totalW / 2;
    const boxY = y - totalH / 2;

    this.ctx.beginPath();
    this.ctx.roundRect(boxX, boxY, totalW, totalH, 4);
    this.ctx.fillStyle = bgColor;
    this.ctx.fill();
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
    this.ctx.lineWidth = 0.75;
    this.ctx.stroke();

    this.ctx.fillStyle = '#ffffff';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'middle';
    this.ctx.fillText(text, x, y);
  }

  private drawTempLabel(x: number, y: number, displayTemp: number, tempC: number) {
    const text = `${displayTemp}°`;
    this.ctx.font = 'bold 11px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const textMetrics = this.ctx.measureText(text);
    const textW = textMetrics.width;

    const padX = 6;
    const totalW = textW + padX * 2;
    const totalH = 18;
    const radius = 4;

    const boxX = x - totalW / 2;
    const boxY = y - totalH / 2;

    let bgColor = 'rgba(28, 41, 65, 0.88)';
    if (tempC >= 38) bgColor = '#b91c1c';
    else if (tempC >= 30) bgColor = '#c2410c';
    else if (tempC >= 22) bgColor = '#a16207';
    else if (tempC >= 15) bgColor = '#15803d';
    else if (tempC >= 5) bgColor = '#0e7490';
    else bgColor = '#1e3a8a';

    this.ctx.beginPath();
    this.ctx.roundRect(boxX, boxY, totalW, totalH, radius);
    this.ctx.fillStyle = bgColor;
    this.ctx.fill();
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
    this.ctx.lineWidth = 0.75;
    this.ctx.stroke();

    this.ctx.fillStyle = '#ffffff';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'middle';
    this.ctx.fillText(text, x, y);
  }

  private drawWindLabel(x: number, y: number, displaySpeed: number, bearingDeg: number, speedKnots: number) {
    const text = `${displaySpeed}`;
    this.ctx.font = 'bold 11px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const textMetrics = this.ctx.measureText(text);
    const textW = textMetrics.width;

    const arrowW = 10;
    const gap = 3;
    const padX = 5;
    const totalW = arrowW + gap + textW + padX * 2;
    const totalH = 18;
    const radius = 4;

    const boxX = x - totalW / 2;
    const boxY = y - totalH / 2;

    let bgColor = 'rgba(28, 41, 65, 0.88)';
    if (speedKnots >= 24) {
      bgColor = '#d9532f';
    } else if (speedKnots >= 18) {
      bgColor = '#a68218';
    } else if (speedKnots >= 9) {
      bgColor = '#3b7829';
    } else if (speedKnots <= 3) {
      bgColor = 'rgba(30, 48, 88, 0.82)';
    }

    this.ctx.beginPath();
    this.ctx.roundRect(boxX, boxY, totalW, totalH, radius);
    this.ctx.fillStyle = bgColor;
    this.ctx.fill();
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
    this.ctx.lineWidth = 0.75;
    this.ctx.stroke();

    const arrowCenterX = boxX + padX + arrowW / 2;
    const arrowCenterY = y;

    this.ctx.save();
    this.ctx.translate(arrowCenterX, arrowCenterY);
    this.ctx.rotate((bearingDeg * Math.PI) / 180);

    this.ctx.beginPath();
    this.ctx.moveTo(0, -4.5);
    this.ctx.lineTo(3.5, 4);
    this.ctx.lineTo(0, 2);
    this.ctx.lineTo(-3.5, 4);
    this.ctx.closePath();
    this.ctx.fillStyle = '#ffffff';
    this.ctx.fill();
    this.ctx.restore();

    this.ctx.fillStyle = '#ffffff';
    this.ctx.textAlign = 'left';
    this.ctx.textBaseline = 'middle';
    this.ctx.fillText(text, boxX + padX + arrowW + gap, y);
  }
}
