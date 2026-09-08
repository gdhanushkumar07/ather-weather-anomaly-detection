import type { CustomLayerInterface, Map as MapLibreMap } from 'maplibre-gl';
import { assertWebGL2, compileProgram, mercator, projectionMatrix } from './gl';

const PARTICLE_VERT = `#version 300 es
in vec2 a_pos;
uniform mat4 u_matrix;
uniform float u_point_size;
void main() {
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
  gl_PointSize = u_point_size;
}`;

const PARTICLE_FRAG = `#version 300 es
precision highp float;
uniform vec4 u_color;
out vec4 fragColor;
void main() {
  vec2 coord = gl_PointCoord - vec2(0.5);
  if (length(coord) > 0.5) discard;
  fragColor = u_color;
}`;

export interface WindGridData {
  nx: number;
  ny: number;
  bbox: [number, number, number, number];
  u: number[];
  v: number[];
}

export class VaneParticlesLayer implements CustomLayerInterface {
  id = 'vane-wind-layer';
  type = 'custom' as const;
  renderingMode = '2d' as const;

  private gl: WebGL2RenderingContext | null = null;
  private map: MapLibreMap | null = null;
  private program: WebGLProgram | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private vbo: WebGLBuffer | null = null;

  private windData: WindGridData;
  private numParticles = 2500;
  private particlePositions: Float32Array; // mercator [x, y]
  private particleAges: Float32Array;
  private animId: number | null = null;

  constructor(windData: WindGridData) {
    this.windData = windData;
    this.particlePositions = new Float32Array(this.numParticles * 2);
    this.particleAges = new Float32Array(this.numParticles);
    this.seedParticles();
  }

  private seedParticles() {
    for (let i = 0; i < this.numParticles; i++) {
      this.resetParticle(i);
      this.particleAges[i] = Math.random() * 100;
    }
  }

  private resetParticle(i: number) {
    // Random position in mercator [0..1]
    const lon = (Math.random() - 0.5) * 360;
    const lat = (Math.random() - 0.5) * 140;
    const [mx, my] = mercator(lon, lat);
    this.particlePositions[i * 2] = mx;
    this.particlePositions[i * 2 + 1] = my;
    this.particleAges[i] = 0;
  }

  onAdd(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
    const gl2 = assertWebGL2(gl);
    this.gl = gl2;
    this.map = map;

    this.program = compileProgram(gl2, PARTICLE_VERT, PARTICLE_FRAG, { a_pos: 0 });

    this.vao = gl2.createVertexArray();
    gl2.bindVertexArray(this.vao);
    this.vbo = gl2.createBuffer();
    gl2.bindBuffer(gl2.ARRAY_BUFFER, this.vbo);
    gl2.bufferData(gl2.ARRAY_BUFFER, this.particlePositions, gl2.DYNAMIC_DRAW);
    gl2.enableVertexAttribArray(0);
    gl2.vertexAttribPointer(0, 2, gl2.FLOAT, false, 0, 0);

    const animate = () => {
      this.updateParticles();
      if (this.map) {
        this.map.triggerRepaint();
      }
      this.animId = requestAnimationFrame(animate);
    };
    this.animId = requestAnimationFrame(animate);
  }

  private sampleWind(mx: number, my: number): [number, number] {
    // Convert mercator back to lon, lat
    const lon = mx * 360 - 180;
    const lat = degrees(2.0 * Math.atan(Math.exp(Math.PI * (1.0 - 2.0 * my))) - Math.PI * 0.5);

    const [w, s, e, n] = this.windData.bbox;
    const u_norm = (lon - w) / (e - w);
    const v_norm = (n - lat) / (n - s);

    if (u_norm < 0 || u_norm > 1 || v_norm < 0 || v_norm > 1) {
      return [0, 0];
    }

    const gx = Math.floor(u_norm * (this.windData.nx - 1));
    const gy = Math.floor(v_norm * (this.windData.ny - 1));
    const idx = gy * this.windData.nx + gx;

    const u = this.windData.u[idx] ?? 0;
    const v = this.windData.v[idx] ?? 0;
    return [u, v];
  }

  private updateParticles() {
    const speedScale = 0.00015;
    for (let i = 0; i < this.numParticles; i++) {
      this.particleAges[i]++;
      if (this.particleAges[i] > 120) {
        this.resetParticle(i);
        continue;
      }

      const mx = this.particlePositions[i * 2];
      const my = this.particlePositions[i * 2 + 1];
      const [u, v] = this.sampleWind(mx, my);

      // Advance particle (u is eastward -> mx increases, v is northward -> my decreases in mercator)
      let nextMx = mx + u * speedScale;
      let nextMy = my - v * speedScale;

      if (nextMx < 0 || nextMx > 1 || nextMy < 0 || nextMy > 1) {
        this.resetParticle(i);
      } else {
        this.particlePositions[i * 2] = nextMx;
        this.particlePositions[i * 2 + 1] = nextMy;
      }
    }

    if (this.gl && this.vbo) {
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.vbo);
      this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, this.particlePositions);
    }
  }

  render(gl: WebGLRenderingContext | WebGL2RenderingContext, matrixOrOptions: unknown): void {
    const gl2 = assertWebGL2(gl);
    if (!this.program || !this.vao) return;

    gl2.useProgram(this.program);
    gl2.bindVertexArray(this.vao);

    gl2.enable(gl2.BLEND);
    gl2.blendFunc(gl2.SRC_ALPHA, gl2.ONE_MINUS_SRC_ALPHA);

    const matrix = projectionMatrix(matrixOrOptions);
    gl2.uniformMatrix4fv(gl2.getUniformLocation(this.program, 'u_matrix'), false, matrix);
    gl2.uniform1f(gl2.getUniformLocation(this.program, 'u_point_size'), 3.0);
    gl2.uniform4f(gl2.getUniformLocation(this.program, 'u_color'), 0.05, 0.45, 0.85, 0.85);

    gl2.drawArrays(gl2.POINTS, 0, this.numParticles);
  }

  onRemove(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
    if (this.animId) cancelAnimationFrame(this.animId);
    const gl2 = assertWebGL2(gl);
    if (this.vbo) gl2.deleteBuffer(this.vbo);
    if (this.vao) gl2.deleteVertexArray(this.vao);
    if (this.program) gl2.deleteProgram(this.program);
    this.gl = null;
    this.map = null;
  }
}

function degrees(rad: number) {
  return (rad * 180) / Math.PI;
}
