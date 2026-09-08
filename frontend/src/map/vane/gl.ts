/**
 * WebGL2 helpers adapted from Vane (Apache-2.0, (c) Rijwind contributors)
 */

export function compileProgram(
  gl: WebGL2RenderingContext,
  vertexSource: string,
  fragmentSource: string,
  attribLocations?: Record<string, number>
): WebGLProgram {
  const program = gl.createProgram();
  if (!program) throw new Error('failed to create program');

  for (const [name, location] of Object.entries(attribLocations ?? {})) {
    gl.bindAttribLocation(program, location, name);
  }

  for (const [type, source] of [
    [gl.VERTEX_SHADER, vertexSource],
    [gl.FRAGMENT_SHADER, fragmentSource],
  ] as const) {
    const shader = gl.createShader(type);
    if (!shader) throw new Error('failed to create shader');
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(`shader compile failed: ${gl.getShaderInfoLog(shader)}\n${source}`);
    }
    gl.attachShader(program, shader);
  }

  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`program link failed: ${gl.getProgramInfoLog(program)}`);
  }
  return program;
}

export function assertWebGL2(gl: WebGLRenderingContext | WebGL2RenderingContext): WebGL2RenderingContext {
  if (!(gl instanceof WebGL2RenderingContext)) {
    throw new Error('Vane layers require a WebGL2 map context');
  }
  return gl;
}

export function projectionMatrix(matrixOrOptions: unknown): Float32Array {
  if (
    Array.isArray(matrixOrOptions) ||
    matrixOrOptions instanceof Float32Array ||
    matrixOrOptions instanceof Float64Array
  ) {
    return new Float32Array(matrixOrOptions as ArrayLike<number>);
  }
  const options = matrixOrOptions as {
    defaultProjectionData?: { mainMatrix: ArrayLike<number> };
    modelViewProjectionMatrix?: ArrayLike<number>;
  };
  const matrix = options.defaultProjectionData?.mainMatrix ?? options.modelViewProjectionMatrix;
  if (!matrix) throw new Error('cannot extract projection matrix');
  return new Float32Array(matrix);
}

export const MAX_MERCATOR_LAT = 85.051129;

export function mercator(lon: number, lat: number): [number, number] {
  const clamped = Math.min(Math.max(lat, -MAX_MERCATOR_LAT), MAX_MERCATOR_LAT);
  const x = (lon + 180) / 360;
  const y = (1 - Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360)) / Math.PI) / 2;
  return [x, y];
}
