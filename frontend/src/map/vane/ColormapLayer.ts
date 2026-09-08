import type { CustomLayerInterface, Map as MapLibreMap } from 'maplibre-gl';
import { assertWebGL2, compileProgram, mercator, projectionMatrix } from './gl';
import { buildLut, TEMPERATURE_CLIM, TEMPERATURE_STOPS } from './colormaps';

const VERTEX_SHADER = `#version 300 es
in vec2 a_uv;
uniform mat4 u_matrix;
uniform vec4 u_merc; // mercator x0,y0 (nw) .. x1,y1 (se)
out vec2 v_merc;
void main() {
  vec2 pos = mix(u_merc.xy, u_merc.zw, a_uv);
  v_merc = pos;
  gl_Position = u_matrix * vec4(pos, 0.0, 1.0);
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec2 v_merc;
uniform sampler2D u_field;
uniform sampler2D u_lut;
uniform vec4 u_bbox; // west, south, east, north (degrees)
uniform vec2 u_clim;
uniform float u_opacity;
out vec4 fragColor;
const float PI = 3.141592653589793;

void main() {
  float lon = v_merc.x * 360.0 - 180.0;
  float lat = degrees(2.0 * atan(exp(PI * (1.0 - 2.0 * v_merc.y))) - PI * 0.5);
  vec2 uv = vec2((lon - u_bbox.x) / (u_bbox.z - u_bbox.x),
                 (u_bbox.w - lat) / (u_bbox.w - u_bbox.y));
  if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) discard;
  float val = texture(u_field, uv).r;
  if (isnan(val)) discard;
  float normalized = clamp((val - u_clim.x) / (u_clim.y - u_clim.x), 0.0, 1.0);
  vec4 col = texture(u_lut, vec2(normalized, 0.5));
  fragColor = vec4(col.rgb, col.a * u_opacity);
}`;

export interface GridFieldData {
  nx: number;
  ny: number;
  bbox: [number, number, number, number];
  data: number[];
  clim?: [number, number];
}

export class VaneColormapLayer implements CustomLayerInterface {
  id = 'vane-temperature-layer';
  type = 'custom' as const;
  renderingMode = '2d' as const;

  private gl: WebGL2RenderingContext | null = null;
  private program: WebGLProgram | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private vbo: WebGLBuffer | null = null;
  private fieldTexture: WebGLTexture | null = null;
  private lutTexture: WebGLTexture | null = null;

  private fieldData: GridFieldData;
  private opacity = 0.72;
  private clim: [number, number] = TEMPERATURE_CLIM;

  constructor(fieldData: GridFieldData) {
    this.fieldData = fieldData;
    if (fieldData.clim) this.clim = fieldData.clim;
  }

  onAdd(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
    const gl2 = assertWebGL2(gl);
    this.gl = gl2;

    this.program = compileProgram(gl2, VERTEX_SHADER, FRAGMENT_SHADER, { a_uv: 0 });

    // Full quad geometry [0,0] to [1,1]
    const quad = new Float32Array([0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1]);
    this.vao = gl2.createVertexArray();
    gl2.bindVertexArray(this.vao);
    this.vbo = gl2.createBuffer();
    gl2.bindBuffer(gl2.ARRAY_BUFFER, this.vbo);
    gl2.bufferData(gl2.ARRAY_BUFFER, quad, gl2.STATIC_DRAW);
    gl2.enableVertexAttribArray(0);
    gl2.vertexAttribPointer(0, 2, gl2.FLOAT, false, 0, 0);

    // Build LUT texture
    const lutBytes = buildLut(TEMPERATURE_STOPS, this.clim);
    this.lutTexture = gl2.createTexture();
    gl2.bindTexture(gl2.TEXTURE_2D, this.lutTexture);
    gl2.texImage2D(gl2.TEXTURE_2D, 0, gl2.RGBA8, 256, 1, 0, gl2.RGBA, gl2.UNSIGNED_BYTE, lutBytes);
    gl2.texParameteri(gl2.TEXTURE_2D, gl2.TEXTURE_MIN_FILTER, gl2.LINEAR);
    gl2.texParameteri(gl2.TEXTURE_2D, gl2.TEXTURE_MAG_FILTER, gl2.LINEAR);
    gl2.texParameteri(gl2.TEXTURE_2D, gl2.TEXTURE_WRAP_S, gl2.CLAMP_TO_EDGE);
    gl2.texParameteri(gl2.TEXTURE_2D, gl2.TEXTURE_WRAP_T, gl2.CLAMP_TO_EDGE);

    // Upload Field Texture (Float32 -> R16F/R32F)
    this.uploadFieldData(this.fieldData);
  }

  public updateField(newField: GridFieldData) {
    this.fieldData = newField;
    if (newField.clim) this.clim = newField.clim;
    if (this.gl) {
      this.uploadFieldData(newField);
    }
  }

  private uploadFieldData(field: GridFieldData) {
    if (!this.gl) return;
    const gl = this.gl;
    const { nx, ny, data } = field;

    const floatData = new Float32Array(data);
    if (!this.fieldTexture) {
      this.fieldTexture = gl.createTexture();
    }
    gl.bindTexture(gl.TEXTURE_2D, this.fieldTexture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, nx, ny, 0, gl.RED, gl.FLOAT, floatData);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  render(gl: WebGLRenderingContext | WebGL2RenderingContext, matrixOrOptions: unknown): void {
    const gl2 = assertWebGL2(gl);
    if (!this.program || !this.vao || !this.fieldTexture || !this.lutTexture) return;

    gl2.useProgram(this.program);
    gl2.bindVertexArray(this.vao);

    gl2.enable(gl2.BLEND);
    gl2.blendFunc(gl2.SRC_ALPHA, gl2.ONE_MINUS_SRC_ALPHA);

    // Set matrix
    const matrix = projectionMatrix(matrixOrOptions);
    const uMatrix = gl2.getUniformLocation(this.program, 'u_matrix');
    gl2.uniformMatrix4fv(uMatrix, false, matrix);

    // Compute Mercator corners
    const [w, s, e, n] = this.fieldData.bbox;
    const [x0, y0] = mercator(w, n);
    const [x1, y1] = mercator(e, s);
    gl2.uniform4f(gl2.getUniformLocation(this.program, 'u_merc'), x0, y0, x1, y1);
    gl2.uniform4f(gl2.getUniformLocation(this.program, 'u_bbox'), w, s, e, n);
    gl2.uniform2f(gl2.getUniformLocation(this.program, 'u_clim'), this.clim[0], this.clim[1]);
    gl2.uniform1f(gl2.getUniformLocation(this.program, 'u_opacity'), this.opacity);

    // Bind textures
    gl2.activeTexture(gl2.TEXTURE0);
    gl2.bindTexture(gl2.TEXTURE_2D, this.fieldTexture);
    gl2.uniform1i(gl2.getUniformLocation(this.program, 'u_field'), 0);

    gl2.activeTexture(gl2.TEXTURE1);
    gl2.bindTexture(gl2.TEXTURE_2D, this.lutTexture);
    gl2.uniform1i(gl2.getUniformLocation(this.program, 'u_lut'), 1);

    gl2.drawArrays(gl2.TRIANGLES, 0, 6);
  }

  onRemove(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
    const gl2 = assertWebGL2(gl);
    if (this.fieldTexture) gl2.deleteTexture(this.fieldTexture);
    if (this.lutTexture) gl2.deleteTexture(this.lutTexture);
    if (this.vbo) gl2.deleteBuffer(this.vbo);
    if (this.vao) gl2.deleteVertexArray(this.vao);
    if (this.program) gl2.deleteProgram(this.program);
    this.gl = null;
  }
}
