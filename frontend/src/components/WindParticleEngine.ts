import L from 'leaflet';
import { computeWindVector } from '../utils/windMath';

export interface Particle {
  x: number;
  y: number;
  age: number;
  maxAge: number;
  speed: number;
}

export class WindParticleEngine {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private map: L.Map;
  private particles: Particle[] = [];
  private numParticles = 900;
  private animationFrameId: number | null = null;
  private isRunning = false;
  private width = 0;
  private height = 0;
  private timeOffsetHours = 0;
  private densityMultiplier = 1;
  private speedScale = 0.85;
  private altitudeLevel = 'surface';

  constructor(map: L.Map, canvas: HTMLCanvasElement) {
    this.map = map;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: true })!;
    this.resize();
    this.initParticles();
  }

  public setTimeOffset(hours: number) {
    this.timeOffsetHours = hours;
  }

  public setAltitudeLevel(alt: string) {
    this.altitudeLevel = alt;
  }

  public setDensity(multiplier: number) {
    this.densityMultiplier = multiplier;
    this.numParticles = Math.floor(900 * multiplier);
    this.initParticles();
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
  }

  public initParticles() {
    this.particles = [];
    for (let i = 0; i < this.numParticles; i++) {
      this.particles.push(this.createRandomParticle());
    }
  }

  private createRandomParticle(): Particle {
    return {
      x: Math.random() * this.width,
      y: Math.random() * this.height,
      age: Math.floor(Math.random() * 45),
      maxAge: 40 + Math.floor(Math.random() * 40),
      speed: 10,
    };
  }

  public start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.animate();
  }

  public stop() {
    this.isRunning = false;
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
    this.clear();
  }

  public clear() {
    this.ctx.clearRect(0, 0, this.width, this.height);
  }

  /**
   * Evaluates wind vector (u: eastward, v: northward) in km/h at a given latitude and longitude.
   * Incorporates planetary trade winds, westerlies, Coriolis deflection,
   * atmospheric pressure depressions, and cyclone vortices.
   */
  public getWindVector(lat: number, lon: number, timeH: number = 0): { u: number; v: number; speed: number; dirDeg: number; speedKnots: number; bearingDeg: number } {
    return computeWindVector(lat, lon, timeH, this.altitudeLevel);
  }

  private animate = () => {
    if (!this.isRunning) return;

    // Trail fading using destination-out to smoothly erase previous frame trails
    // while keeping unpainted canvas areas 100% transparent so map tiles remain visible
    this.ctx.globalCompositeOperation = 'destination-out';
    this.ctx.fillStyle = 'rgba(0, 0, 0, 0.09)';
    this.ctx.fillRect(0, 0, this.width, this.height);
    this.ctx.globalCompositeOperation = 'source-over';

    const zoom = this.map.getZoom();
    const pixelScale = Math.pow(2, zoom - 5) * 0.045 * this.speedScale;

    // Batch draw lines with color grouping
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];

      // Convert pixel position to LatLng
      const latLng = this.map.containerPointToLatLng(L.point(p.x, p.y));
      const vector = this.getWindVector(latLng.lat, latLng.lng, this.timeOffsetHours);
      p.speed = vector.speed;

      // Project motion onto screen pixels
      const dx = vector.u * pixelScale;
      // Latitude increases northward, whereas canvas Y increases southward
      const dy = -vector.v * pixelScale;

      const nextX = p.x + dx;
      const nextY = p.y + dy;

      // Draw particle line
      this.ctx.beginPath();
      this.ctx.moveTo(p.x, p.y);
      this.ctx.lineTo(nextX, nextY);
      this.ctx.strokeStyle = this.getColor(vector.speed, p.age, p.maxAge);
      this.ctx.lineWidth = Math.min(2.0, Math.max(1.0, vector.speed / 24));
      this.ctx.lineCap = 'round';
      this.ctx.stroke();

      p.x = nextX;
      p.y = nextY;
      p.age++;

      // Respawn conditions
      if (
        p.age > p.maxAge ||
        p.x < 0 ||
        p.x > this.width ||
        p.y < 0 ||
        p.y > this.height ||
        Math.random() < 0.015
      ) {
        this.particles[i] = this.createRandomParticle();
      }
    }

    this.animationFrameId = requestAnimationFrame(this.animate);
  };

  /**
   * Color ramp for wind velocity matching atmospheric velocity field
   */
  public getColor(speedKmh: number, age = 20, maxAge = 50): string {
    const opacity = Math.sin((age / maxAge) * Math.PI) * 0.85 + 0.15;
    const alpha = opacity.toFixed(2);

    if (speedKmh < 10) return `rgba(165, 214, 255, ${alpha})`; // Soft cyan
    if (speedKmh < 22) return `rgba(56, 189, 248, ${alpha})`;  // Sky blue
    if (speedKmh < 36) return `rgba(52, 211, 153, ${alpha})`;  // Emerald
    if (speedKmh < 50) return `rgba(250, 204, 21, ${alpha})`;  // Bright yellow
    if (speedKmh < 68) return `rgba(251, 146, 60, ${alpha})`;  // Amber orange
    if (speedKmh < 90) return `rgba(239, 68, 68, ${alpha})`;   // Crimson
    return `rgba(217, 70, 239, ${alpha})`;                     // Purple / magenta extreme
  }
}
