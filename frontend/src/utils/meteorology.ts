/**
 * High-precision meteorological field models and synoptic physics engine.
 * Fully aligned with geographic coordinates, planetary circulation,
 * Rossby waves, frontal zones, and cyclonic vortex dynamics.
 */

// --- Synoptic Centers Shared with Wind Model ---

export interface SynopticCenter {
  lat: number;
  lon: number;
  type: 'L' | 'H';
  pCentral: number; // Central pressure in hPa
  radiusDeg: number;
  name: string;
}

export function getSynopticCenters(timeH: number = 0): SynopticCenter[] {
  const timeFactor = timeH * 0.08;

  // 1. Bay of Bengal Cyclonic Depression (tracks WNW towards coastal India)
  const bobLat = 16.5 + Math.sin(timeFactor * 0.2) * 2.5;
  const bobLon = 86.0 + Math.cos(timeFactor * 0.15) * 3.0;

  // 2. West Pacific Typhoon (tracks WNW towards Taiwan / Ryukyu)
  const typLat = 21.0 + Math.sin(timeFactor * 0.1) * 3.0;
  const typLon = 132.0 + Math.cos(timeFactor * 0.08) * 4.0;

  // 3. North Atlantic Cyclonic Low (Icelandic Low / Frontal Wave)
  const atlLat = 52.0 + Math.cos(timeFactor * 0.1) * 3.0;
  const atlLon = -32.0 + Math.sin(timeFactor * 0.1) * 6.0;

  // 4. North Pacific Low (Aleutian Low)
  const pacLat = 53.0 + Math.cos(timeFactor * 0.08) * 2.5;
  const pacLon = -168.0 + Math.sin(timeFactor * 0.08) * 4.0;

  // 5. Azores Subtropical High
  const azLat = 33.0;
  const azLon = -36.0;

  // 6. North Pacific Subtropical High
  const nphLat = 34.0;
  const nphLon = -142.0;

  // 7. Siberian Continental High
  const sibLat = 50.0;
  const sibLon = 96.0;

  // 8. Mascarene High (South Indian Ocean)
  const mascLat = -30.0;
  const mascLon = 76.0;

  return [
    { lat: bobLat, lon: bobLon, type: 'L', pCentral: 980, radiusDeg: 12.0, name: 'Bay of Bengal Cyclone' },
    { lat: typLat, lon: typLon, type: 'L', pCentral: 968, radiusDeg: 14.0, name: 'Typhoon Core' },
    { lat: atlLat, lon: atlLon, type: 'L', pCentral: 984, radiusDeg: 18.0, name: 'North Atlantic Low' },
    { lat: pacLat, lon: pacLon, type: 'L', pCentral: 988, radiusDeg: 18.0, name: 'Aleutian Low' },
    { lat: azLat, lon: azLon, type: 'H', pCentral: 1028, radiusDeg: 22.0, name: 'Azores High' },
    { lat: nphLat, lon: nphLon, type: 'H', pCentral: 1026, radiusDeg: 24.0, name: 'Pacific High' },
    { lat: sibLat, lon: sibLon, type: 'H', pCentral: 1032, radiusDeg: 22.0, name: 'Siberian High' },
    { lat: mascLat, lon: mascLon, type: 'H', pCentral: 1026, radiusDeg: 20.0, name: 'Mascarene High' },
  ];
}

// --- 1. Authentic Continuous Barometric Pressure Field (hPa) ---

export function computePressure(lat: number, lon: number, timeH: number = 0): number {
  const radLat = (lat * Math.PI) / 180;
  const cosLat = Math.cos(radLat);
  const absLat = Math.abs(lat);
  const timeFactor = timeH * 0.08;

  // Global planetary barometric zonal belts:
  // - Equatorial Low (ITCZ, ~1010 hPa)
  // - Subtropical High Pressure Ridge (~1018-1024 hPa at 25-35 deg)
  // - Subpolar Low Pressure Troughs (~995-1005 hPa at 50-65 deg)
  // - Polar High (~1015 hPa at poles)
  let p = 1013.25;
  if (absLat < 20) {
    p = 1009.0 + 4.0 * Math.pow(absLat / 20, 2);
  } else if (absLat >= 20 && absLat < 48) {
    p = 1017.5 + 4.5 * Math.sin(((absLat - 20) * Math.PI) / 28);
  } else if (absLat >= 48 && absLat < 72) {
    p = 1004.0 - 10.0 * Math.sin(((absLat - 48) * Math.PI) / 24);
  } else {
    p = 1014.0 + 4.0 * Math.cos(((absLat - 72) * Math.PI) / 36);
  }

  // Rossby planetary wave modulation
  const wave = 4.5 * Math.sin(((lon + timeFactor * 10) * Math.PI) / 60) * Math.sin(radLat * 1.5);
  p += wave;

  // Synoptic Highs and Lows
  const centers = getSynopticCenters(timeH);
  for (let i = 0; i < centers.length; i++) {
    const c = centers[i];
    const dLat = lat - c.lat;
    const dLon = (lon - c.lon) * cosLat;
    const dist = Math.sqrt(dLat * dLat + dLon * dLon);

    if (dist < c.radiusDeg) {
      const falloff = Math.pow(1 - dist / c.radiusDeg, 2);
      const deltaP = c.pCentral - 1013.25;
      p += deltaP * falloff * 0.95;
    }
  }

  return Math.round(p * 10) / 10;
}

// --- 2. Authentic Continuous Precipitation Field (mm/h) ---

export function computePrecipitation(lat: number, lon: number, timeH: number = 0): number {
  const radLat = (lat * Math.PI) / 180;
  const cosLat = Math.cos(radLat);
  const timeFactor = timeH * 0.08;
  let totalRain = 0;

  // 1. Bay of Bengal Cyclonic Spiral Bands
  const bobLat = 16.5 + Math.sin(timeFactor * 0.2) * 2.5;
  const bobLon = 86.0 + Math.cos(timeFactor * 0.15) * 3.0;
  const dLatBob = lat - bobLat;
  const dLonBob = (lon - bobLon) * cosLat;
  const distBob = Math.sqrt(dLatBob * dLatBob + dLonBob * dLonBob);

  if (distBob < 9.5) {
    const angleBob = Math.atan2(dLatBob, dLonBob);
    // Eyewall convective core
    const eyewall = Math.exp(-Math.pow(distBob, 2) / 3.2) * 48;
    // Logarithmic cyclonic spiral feeder bands: r = a * exp(b * theta)
    const spiralPhase = 2.8 * angleBob - distBob * 0.85;
    const spiralArms = Math.exp(-Math.pow(distBob, 2) / 26) * Math.max(0, Math.cos(spiralPhase)) * 26;
    totalRain += eyewall + spiralArms;
  }

  // 2. West Pacific Typhoon System
  const typLat = 21.0 + Math.sin(timeFactor * 0.1) * 3.0;
  const typLon = 132.0 + Math.cos(timeFactor * 0.08) * 4.0;
  const dLatTyp = lat - typLat;
  const dLonTyp = (lon - typLon) * cosLat;
  const distTyp = Math.sqrt(dLatTyp * dLatTyp + dLonTyp * dLonTyp);

  if (distTyp < 10.5) {
    const angleTyp = Math.atan2(dLatTyp, dLonTyp);
    const eyewall = Math.exp(-Math.pow(distTyp, 2) / 3.8) * 56;
    const spiralPhase = 3.0 * angleTyp - distTyp * 0.78;
    const spiralArms = Math.exp(-Math.pow(distTyp, 2) / 30) * Math.max(0, Math.cos(spiralPhase)) * 30;
    totalRain += eyewall + spiralArms;
  }

  // 3. Indian Western Ghats Orographic Rain Swath (8.5N to 19.5N, 73E to 76.5E)
  if (lat >= 8.5 && lat <= 20.0 && lon >= 72.5 && lon <= 76.8) {
    const ridgeLon = 73.4 + (lat - 8.5) * 0.16;
    const dRidge = Math.abs(lon - ridgeLon);
    if (dRidge < 1.5) {
      totalRain += Math.exp(-Math.pow(dRidge, 2) / 0.65) * (20 + 5 * Math.sin(lat * 0.5 + timeFactor * 0.5));
    }
  }

  // 4. Northeast India / Bangladesh Monsoon Trough (21N-27N, 88E-94E)
  if (lat >= 21.0 && lat <= 27.0 && lon >= 88.0 && lon <= 94.5) {
    const dNe = Math.hypot((lat - 24.2) * 0.7, (lon - 91.0) * 0.45);
    if (dNe < 4.5) {
      totalRain += Math.exp(-Math.pow(dNe, 2) / 7.0) * 24;
    }
  }

  // 5. North Atlantic Frontal Rainband
  if (lon >= -55 && lon <= 5 && lat >= 38 && lat <= 64) {
    const frontLat = 47.0 + (lon + 30) * 0.38 - Math.pow((lon + 15) * 0.03, 2) + Math.sin(timeFactor * 0.3) * 2.0;
    const dFront = Math.abs(lat - frontLat);
    if (dFront < 3.2) {
      totalRain += Math.exp(-Math.pow(dFront, 2) / 2.2) * (14 + 4 * Math.sin(lon * 0.15));
    }
  }

  // 6. Equatorial Intertropical Convergence Zone (ITCZ) discrete convective storms
  const itczCells = [
    { lat: 6.8, lon: -115.0 + timeH * 0.08, max: 24 },
    { lat: 6.2, lon: -142.0 + timeH * 0.08, max: 20 },
    { lat: 5.2, lon: -28.0 + timeH * 0.08, max: 22 },
    { lat: 4.8, lon: 93.0 + timeH * 0.05, max: 25 },
    { lat: 2.2, lon: 122.0 + timeH * 0.04, max: 26 },
    { lat: -3.2, lon: -62.0, max: 19 }, // Amazon Basin
    { lat: 1.2, lon: 23.5, max: 18 },  // Congo Basin
  ];

  for (let i = 0; i < itczCells.length; i++) {
    const cell = itczCells[i];
    const d = Math.hypot(lat - cell.lat, (lon - cell.lon) * cosLat);
    if (d < 4.2) {
      totalRain += Math.exp(-Math.pow(d, 2) / 5.5) * cell.max;
    }
  }

  return Math.round(totalRain * 10) / 10;
}

// --- 3. Doppler Radar Reflectivity (dBZ) ---

export function computeRadarDbz(lat: number, lon: number, timeH: number = 0): number {
  const rain = computePrecipitation(lat, lon, timeH);
  if (rain < 0.15) return 0;
  // Marshall-Palmer relation: Z = 200 * R^1.6 -> dBZ = 10 * log10(Z)
  const z = 200 * Math.pow(rain, 1.6);
  const dbz = 10 * Math.log10(Math.max(1, z));
  return Math.round(Math.min(72, Math.max(14, dbz)));
}

// --- 4. Authentic Planetary Temperature Field (°C) ---

export function computeTemperature(lat: number, lon: number, timeH: number = 0, altitudeLevel = 'surface'): number {
  const radLat = (lat * Math.PI) / 180;
  const absLat = Math.abs(lat);

  // 1. Planetary insolation balance (Tropics ~28-32C down to Polar ice ~ -25C to -45C)
  let t = 31.0 * Math.cos(radLat * 0.96) - 22.0 * Math.pow(Math.sin(radLat), 2);

  // 2. Continental Arid Deserts (Intense solar sensible heat flux)
  // Sahara & Arabian Peninsula (15N-32N, -15W-55E)
  if (lat >= 14 && lat <= 32 && lon >= -15 && lon <= 55) {
    const dSahara = Math.hypot((lat - 24) * 0.55, (lon - 20) * 0.18);
    if (dSahara < 8.0) t += (1 - dSahara / 8.0) * 12.0;
  }
  // Thar Desert (NW India / Pakistan, 24N-31N, 68E-76E)
  if (lat >= 23 && lat <= 32 && lon >= 68 && lon <= 77) {
    t += 7.0;
  }
  // Australian Outback (-32S to -18S, 118E-142E)
  if (lat >= -32 && lat <= -18 && lon >= 118 && lon <= 142) {
    t += 6.5;
  }

  // 3. Maritime Ocean Currents
  // Warm Gulf Stream / North Atlantic Drift (30N-52N, -75W to -10W)
  if (lat >= 30 && lat <= 54 && lon >= -75 && lon <= -10) {
    t += 3.5 * Math.exp(-Math.pow(lat - (35 + (lon + 70) * 0.32), 2) / 26);
  }
  // Cold Humboldt Current (West coast of South America)
  if (lat >= -42 && lat <= -4 && lon >= -85 && lon <= -71) {
    t -= 5.0;
  }

  // 4. Orographic Lapse Rate (Adiabatic cooling ~6.5°C/km)
  // Tibetan Plateau (~4500m) & Himalayas
  if (lat >= 27 && lat <= 39 && lon >= 78 && lon <= 104) {
    t -= 22.5;
  }
  // Andes Mountain Range
  if (lat >= -48 && lat <= 8 && lon >= -76 && lon <= -66) {
    t -= 14.0;
  }
  // Rocky Mountains
  if (lat >= 35 && lat <= 58 && lon >= -122 && lon <= -104) {
    t -= 9.0;
  }

  // 5. Diurnal solar cycle
  const solarHour = (((lon + timeH * 15 + 180) % 360) + 360) % 360 / 15;
  const diurnal = 3.5 * Math.cos(((solarHour - 14) * Math.PI) / 12);
  t += diurnal;

  // 6. Altitude level lapse
  if (altitudeLevel === '100m') t -= 0.65;
  else if (altitudeLevel === '900m') t -= 5.85;
  else if (altitudeLevel === '3000m') t -= 19.5;
  else if (altitudeLevel === '5500m') t -= 35.75;
  else if (altitudeLevel === '9000m' || altitudeLevel === 'jetstream') t -= 56.0;

  return Math.round(t * 10) / 10;
}

// --- 5. Authentic Cloud Cover (%) ---

export function computeCloudCover(lat: number, lon: number, timeH: number = 0): number {
  const rain = computePrecipitation(lat, lon, timeH);
  if (rain > 1.0) {
    return Math.min(100, Math.round(78 + rain * 1.2));
  }

  const absLat = Math.abs(lat);
  // Arid deserts have virtually 0-10% cloud cover
  if (absLat >= 16 && absLat <= 32 && lon >= -15 && lon <= 78) {
    return 6;
  }
  if (absLat >= -32 && absLat <= -18 && lon >= 118 && lon <= 142) {
    return 8;
  }

  // Maritime mid-latitudes vs tropics
  const base = absLat > 45 ? 58 : 28;
  const wave = 18 * Math.sin(((lon + timeH * 8) * Math.PI) / 45) * Math.cos((lat * Math.PI) / 30);
  return Math.min(92, Math.max(8, Math.round(base + wave)));
}

// --- 6. Authentic Relative Humidity (%) ---

export function computeHumidity(lat: number, lon: number, timeH: number = 0): number {
  const rain = computePrecipitation(lat, lon, timeH);
  if (rain > 0.5) {
    return Math.min(99, Math.round(86 + rain * 0.6));
  }

  const absLat = Math.abs(lat);
  // Desert dry belts
  if ((absLat >= 16 && absLat <= 32 && lon >= -15 && lon <= 78) || (absLat >= -32 && absLat <= -18 && lon >= 118 && lon <= 142)) {
    return 18;
  }
  // Maritime tropics & mid-latitudes
  return absLat < 22 ? 82 : 68;
}

// --- 7. Convective Storms / CAPE (J/kg) ---

export function computeCape(lat: number, lon: number, timeH: number = 0): number {
  const rain = computePrecipitation(lat, lon, timeH);
  if (rain < 1.0) return 0;
  const temp = computeTemperature(lat, lon, timeH);
  // High instability when high surface moisture and warm temperatures meet
  const inst = Math.max(0, temp - 18) / 14;
  return Math.round(rain * 85 * (1 + inst));
}

// --- Continuous Meteorological Color Ramps (Piecewise Linear, Zero Stepping) ---

export function lerpColor(val: number, stops: [number, [number, number, number, number]][]): [number, number, number, number] {
  if (val <= stops[0][0]) return stops[0][1];
  if (val >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];

  for (let i = 0; i < stops.length - 1; i++) {
    const s0 = stops[i];
    const s1 = stops[i + 1];
    if (val >= s0[0] && val <= s1[0]) {
      const t = (val - s0[0]) / (s1[0] - s0[0]);
      return [
        Math.round(s0[1][0] + t * (s1[1][0] - s0[1][0])),
        Math.round(s0[1][1] + t * (s1[1][1] - s0[1][1])),
        Math.round(s0[1][2] + t * (s1[1][2] - s0[1][2])),
        Math.round(s0[1][3] + t * (s1[1][3] - s0[1][3])),
      ];
    }
  }
  return stops[stops.length - 1][1];
}

// Temperature Color Ramp: -30C deep violet -> -10C blue -> 0C cyan -> 16C teal -> 24C green -> 32C amber -> 42C crimson
export const TEMP_STOPS: [number, [number, number, number, number]][] = [
  [-30, [112, 26, 117, 185]],
  [-15, [59, 130, 246, 180]],
  [-2,  [14, 165, 233, 175]],
  [8,   [13, 148, 136, 175]],
  [18,  [34, 197, 94, 175]],
  [26,  [234, 179, 8, 175]],
  [34,  [249, 115, 22, 180]],
  [44,  [225, 29, 72, 185]],
  [52,  [159, 18, 57, 190]],
];

// Precipitation Rain Rate Color Ramp: 0 mm/h 100% transparent -> cyan -> emerald -> amber -> orange-red -> magenta
export const RAIN_STOPS: [number, [number, number, number, number]][] = [
  [0.0, [0, 0, 0, 0]],
  [0.2, [56, 189, 248, 0]],
  [0.5, [56, 189, 248, 70]],
  [2.0, [34, 197, 94, 145]],
  [6.0, [234, 179, 8, 185]],
  [15.0, [249, 115, 22, 210]],
  [30.0, [239, 68, 68, 230]],
  [50.0, [217, 70, 239, 245]],
];

// Radar Reflectivity (dBZ): 0-14 dBZ 100% transparent -> 15-70 dBZ
export const RADAR_STOPS: [number, [number, number, number, number]][] = [
  [0,   [0, 0, 0, 0]],
  [14,  [74, 222, 128, 0]],
  [20,  [74, 222, 128, 140]],
  [30,  [250, 204, 21, 180]],
  [40,  [249, 115, 22, 210]],
  [50,  [239, 68, 68, 235]],
  [65,  [217, 70, 239, 250]],
];

// Relative Humidity (%): 15% arid amber -> 50% teal -> 85% deep blue
export const HUMIDITY_STOPS: [number, [number, number, number, number]][] = [
  [10, [217, 119, 6, 150]],
  [30, [234, 179, 8, 155]],
  [55, [13, 148, 136, 160]],
  [75, [37, 99, 235, 170]],
  [98, [29, 78, 216, 185]],
];

// Barometric Pressure Color Tint (hPa): <985 red low -> 1013 slate -> >1028 blue high
export const PRESSURE_STOPS: [number, [number, number, number, number]][] = [
  [975,  [225, 29, 72, 160]],
  [992,  [249, 115, 22, 150]],
  [1006, [234, 179, 8, 130]],
  [1013, [148, 163, 184, 100]],
  [1022, [59, 130, 246, 140]],
  [1035, [67, 56, 202, 165]],
];

// --- 8. Marching Squares Isobar Contouring Algorithm ---

export interface IsobarSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  val: number;
}

export interface PressureExtremum {
  x: number;
  y: number;
  lat: number;
  lon: number;
  type: 'L' | 'H';
  value: number;
}

export function extractIsobarsAndExtrema(
  grid: number[][],
  gridW: number,
  gridH: number,
  stepX: number,
  stepY: number,
  isobarInterval: number = 4
): { segments: IsobarSegment[]; extrema: PressureExtremum[] } {
  const segments: IsobarSegment[] = [];
  const extrema: PressureExtremum[] = [];

  // Find overall min and max in grid
  let minP = 1050;
  let maxP = 950;
  for (let r = 0; r < gridH; r++) {
    for (let c = 0; c < gridW; c++) {
      const v = grid[r][c];
      if (v < minP) minP = v;
      if (v > maxP) maxP = v;
    }
  }

  // Determine standard isobar levels (e.g. 984, 988, 992, ..., 1032)
  const startLevel = Math.floor(minP / isobarInterval) * isobarInterval;
  const endLevel = Math.ceil(maxP / isobarInterval) * isobarInterval;

  // Marching squares over 2D cells
  for (let level = startLevel; level <= endLevel; level += isobarInterval) {
    for (let r = 0; r < gridH - 1; r++) {
      const y0 = r * stepY;
      const y1 = (r + 1) * stepY;

      for (let c = 0; c < gridW - 1; c++) {
        const x0 = c * stepX;
        const x1 = (c + 1) * stepX;

        const valTL = grid[r][c];
        const valTR = grid[r][c + 1];
        const valBR = grid[r + 1][c + 1];
        const valBL = grid[r + 1][c];

        let cellIndex = 0;
        if (valTL >= level) cellIndex |= 8;
        if (valTR >= level) cellIndex |= 4;
        if (valBR >= level) cellIndex |= 2;
        if (valBL >= level) cellIndex |= 1;

        if (cellIndex === 0 || cellIndex === 15) continue;

        // Linear interpolation points along edges
        const tTop = valTR !== valTL ? (level - valTL) / (valTR - valTL) : 0.5;
        const ptTop = { x: x0 + tTop * (x1 - x0), y: y0 };

        const tRight = valBR !== valTR ? (level - valTR) / (valBR - valTR) : 0.5;
        const ptRight = { x: x1, y: y0 + tRight * (y1 - y0) };

        const tBottom = valBR !== valBL ? (level - valBL) / (valBR - valBL) : 0.5;
        const ptBottom = { x: x0 + tBottom * (x1 - x0), y: y1 };

        const tLeft = valBL !== valTL ? (level - valTL) / (valBL - valTL) : 0.5;
        const ptLeft = { x: x0, y: y0 + tLeft * (y1 - y0) };

        switch (cellIndex) {
          case 1:
          case 14:
            segments.push({ x1: ptLeft.x, y1: ptLeft.y, x2: ptBottom.x, y2: ptBottom.y, val: level });
            break;
          case 2:
          case 13:
            segments.push({ x1: ptBottom.x, y1: ptBottom.y, x2: ptRight.x, y2: ptRight.y, val: level });
            break;
          case 3:
          case 12:
            segments.push({ x1: ptLeft.x, y1: ptLeft.y, x2: ptRight.x, y2: ptRight.y, val: level });
            break;
          case 4:
          case 11:
            segments.push({ x1: ptTop.x, y1: ptTop.y, x2: ptRight.x, y2: ptRight.y, val: level });
            break;
          case 5:
            segments.push({ x1: ptLeft.x, y1: ptLeft.y, x2: ptTop.x, y2: ptTop.y, val: level });
            segments.push({ x1: ptBottom.x, y1: ptBottom.y, x2: ptRight.x, y2: ptRight.y, val: level });
            break;
          case 6:
          case 9:
            segments.push({ x1: ptTop.x, y1: ptTop.y, x2: ptBottom.x, y2: ptBottom.y, val: level });
            break;
          case 7:
          case 8:
            segments.push({ x1: ptLeft.x, y1: ptLeft.y, x2: ptTop.x, y2: ptTop.y, val: level });
            break;
          case 10:
            segments.push({ x1: ptTop.x, y1: ptTop.y, x2: ptRight.x, y2: ptRight.y, val: level });
            segments.push({ x1: ptLeft.x, y1: ptLeft.y, x2: ptBottom.x, y2: ptBottom.y, val: level });
            break;
        }
      }
    }
  }

  // Find local extrema (H / L)
  for (let r = 2; r < gridH - 2; r += 2) {
    for (let c = 2; c < gridW - 2; c += 2) {
      const v = grid[r][c];
      let isMin = true;
      let isMax = true;

      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          if (dr === 0 && dc === 0) continue;
          const neighbor = grid[r + dr][c + dc];
          if (neighbor <= v) isMin = false;
          if (neighbor >= v) isMax = false;
        }
      }

      if (isMin && v < 1008) {
        extrema.push({ x: c * stepX, y: r * stepY, lat: 0, lon: 0, type: 'L', value: Math.round(v) });
      } else if (isMax && v > 1018) {
        extrema.push({ x: c * stepX, y: r * stepY, lat: 0, lon: 0, type: 'H', value: Math.round(v) });
      }
    }
  }

  return { segments, extrema };
}
