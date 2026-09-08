/**
 * Shared meteorological vector field engine.
 * Computes u/v wind components, speeds, and directions
 * incorporating planetary zonal flows, trade winds, Rossby waves,
 * monsoonal jets (e.g. Somali jet stream), and cyclonic systems.
 */

export interface WindVector {
  u: number; // Eastward speed (km/h)
  v: number; // Northward speed (km/h)
  speed: number; // km/h
  speedKnots: number; // kt
  dirDeg: number; // Meteorological direction (0-360, where wind comes from)
  bearingDeg: number; // Direction wind is heading towards (for rotation)
}

export function computeWindVector(lat: number, lon: number, timeH: number = 0, altitudeLevel = 'surface'): WindVector {
  const radLat = (lat * Math.PI) / 180;
  const radLon = (lon * Math.PI) / 180;
  const timeFactor = timeH * 0.08;

  let u = 0;
  let v = 0;

  const absLat = Math.abs(lat);

  // 1. Global Atmospheric Zonal Circulation
  if (absLat < 28) {
    // Tropical Trade Winds (Easterlies)
    u = -16 * Math.cos(radLat * 1.5);
    v = (lat > 0 ? -6 : 6) * Math.sin(radLat * 2);
  } else if (absLat >= 28 && absLat < 62) {
    // Mid-Latitude Westerlies (Jet Stream)
    const jetBase = altitudeLevel === 'jetstream' || altitudeLevel === '9000m' ? 85 : 25;
    const jetStream = jetBase + 20 * Math.cos((absLat - 45) * (Math.PI / 30));
    u = jetStream * Math.cos(radLat * 0.8);
    v = 8 * Math.sin((lon + timeFactor * 10) * 0.08);
  } else {
    // Polar Easterlies
    u = -14 * Math.cos(radLat);
    v = lat > 0 ? -4 : 4;
  }

  // 2. Synoptic Rossby Waves & atmospheric undulating troughs
  const wave1 = Math.sin(radLon * 3 + timeFactor * 0.5 + radLat * 2);
  const wave2 = Math.cos(radLon * 5 - timeFactor * 0.3);
  u += wave1 * 8;
  v += wave2 * 10;

  // 3. Iconic Somali Low-Level Jet (Findlater Jet):
  // Blows intensely along the coast of Somalia and into the Arabian Sea / Oman
  // Lat 5N to 20N, Lon 45E to 65E
  const somaliLat = 12.0;
  const somaliLon = 54.0;
  const dLatS = lat - somaliLat;
  const dLonS = (lon - somaliLon) * Math.cos(radLat);
  const distS = Math.sqrt(dLatS * dLatS + dLonS * dLonS);
  if (distS < 16) {
    // Strong south-westerly jet stream towards Arabian Sea / India
    const intensity = Math.max(0, 1 - distS / 16) * 44; // speeds up to 28-30 kt
    u += intensity * 0.85;
    v += intensity * 0.75;
  }

  // 4. North Indian Ocean & Bay of Bengal Cyclonic system
  const cyclone1Lat = 16.5 + Math.sin(timeFactor * 0.2) * 2.5;
  const cyclone1Lon = 86.0 + Math.cos(timeFactor * 0.15) * 3.0;
  const dLat1 = lat - cyclone1Lat;
  const dLon1 = (lon - cyclone1Lon) * Math.cos(radLat);
  const dist1 = Math.sqrt(dLat1 * dLat1 + dLon1 * dLon1);

  if (dist1 < 22) {
    const strength1 = Math.max(0, 1 - dist1 / 22) * 58;
    const angle1 = Math.atan2(dLat1, dLon1);
    u += -Math.sin(angle1) * strength1;
    v += Math.cos(angle1) * strength1;
    // Inflow
    u += -Math.cos(angle1) * (strength1 * 0.25);
    v += -Math.sin(angle1) * (strength1 * 0.25);
  }

  // 5. North Atlantic Low / High
  const cyclone2Lat = 50 + Math.cos(timeFactor * 0.1) * 3;
  const cyclone2Lon = -30 + Math.sin(timeFactor * 0.1) * 6;
  const dLat2 = lat - cyclone2Lat;
  const dLon2 = (lon - cyclone2Lon) * Math.cos(radLat);
  const dist2 = Math.sqrt(dLat2 * dLat2 + dLon2 * dLon2);
  if (dist2 < 26) {
    const strength2 = Math.max(0, 1 - dist2 / 26) * 44;
    const angle2 = Math.atan2(dLat2, dLon2);
    u += -Math.sin(angle2) * strength2;
    v += Math.cos(angle2) * strength2;
  }

  // 6. West Pacific Typhoon
  const typhoonLat = 21 + Math.sin(timeFactor * 0.1) * 3;
  const typhoonLon = 132 + Math.cos(timeFactor * 0.08) * 4;
  const dLat3 = lat - typhoonLat;
  const dLon3 = (lon - typhoonLon) * Math.cos(radLat);
  const dist3 = Math.sqrt(dLat3 * dLat3 + dLon3 * dLon3);
  if (dist3 < 20) {
    const strength3 = Math.max(0, 1 - dist3 / 20) * 65;
    const angle3 = Math.atan2(dLat3, dLon3);
    u += -Math.sin(angle3) * strength3;
    v += Math.cos(angle3) * strength3;
  }

  // Altitude scaling
  let altitudeMultiplier = 1.0;
  if (altitudeLevel === '100m') altitudeMultiplier = 1.15;
  else if (altitudeLevel === '900m') altitudeMultiplier = 1.35;
  else if (altitudeLevel === '3000m') altitudeMultiplier = 1.6;
  else if (altitudeLevel === '5500m') altitudeMultiplier = 1.9;
  else if (altitudeLevel === '9000m' || altitudeLevel === 'jetstream') altitudeMultiplier = 2.4;

  u *= altitudeMultiplier;
  v *= altitudeMultiplier;

  const speed = Math.sqrt(u * u + v * v);
  const speedKnots = Math.round(speed / 1.852);

  // Direction wind is coming from (meteorological degrees: 0 = North, 90 = East, 180 = South, 270 = West)
  let dirDeg = (Math.atan2(-u, -v) * 180) / Math.PI;
  if (dirDeg < 0) dirDeg += 360;

  // Direction arrow should point towards (where wind is blowing to):
  let bearingDeg = (Math.atan2(u, v) * 180) / Math.PI;
  if (bearingDeg < 0) bearingDeg += 360;

  return {
    u,
    v,
    speed,
    speedKnots,
    dirDeg: Math.round(dirDeg),
    bearingDeg: Math.round(bearingDeg),
  };
}

/**
 * Returns authentic meteorological color for wind speed in knots
 * Matching standard velocity ramp: 0/5/10/20/30/40/60 kt
 */
export function getWindColorByKnots(knots: number, alpha: number = 0.85): string {
  if (knots <= 2) return `rgba(32, 45, 85, ${alpha * 0.7})`;
  if (knots <= 5) return `rgba(30, 80, 120, ${alpha * 0.75})`;
  if (knots <= 8) return `rgba(32, 120, 100, ${alpha * 0.78})`;
  if (knots <= 12) return `rgba(45, 150, 60, ${alpha * 0.82})`;
  if (knots <= 16) return `rgba(95, 175, 45, ${alpha * 0.84})`;
  if (knots <= 21) return `rgba(215, 180, 25, ${alpha * 0.86})`;
  if (knots <= 28) return `rgba(235, 110, 30, ${alpha * 0.88})`; // Orange, e.g. 27 kt in image.png
  if (knots <= 38) return `rgba(225, 55, 30, ${alpha * 0.90})`;  // Red-orange
  if (knots <= 50) return `rgba(195, 30, 85, ${alpha * 0.92})`;  // Ruby red / crimson
  return `rgba(150, 25, 140, ${alpha * 0.94})`;                  // Purple / magenta
}
