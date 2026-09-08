/**
 * Script to download and parse NOAA Integrated Surface Database (ISD) station history (isd-history.csv)
 * Source: ftp://ftp.ncdc.noaa.gov/pub/data/noaa/isd-history.csv / https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv
 *
 * Generates: public/data/stations.json
 */

import fs from 'fs';
import path from 'path';
import https from 'https';

const NOAA_ISD_URL = 'https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv';
const OUTPUT_DIR = path.resolve(process.cwd(), 'public/data');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'stations.json');

// Ensure output directory exists
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

function parseCSVLine(line) {
  const result = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      result.push(cur.trim());
      cur = '';
    } else {
      cur += char;
    }
  }
  result.push(cur.trim());
  return result.map((s) => s.replace(/^"|"$/g, '').trim());
}

console.log(`Downloading NOAA ISD station history from ${NOAA_ISD_URL}...`);

https
  .get(NOAA_ISD_URL, (res) => {
    if (res.statusCode !== 200) {
      console.error(`Failed to download: HTTP Status ${res.statusCode}`);
      process.exit(1);
    }

    let csvData = '';
    res.on('data', (chunk) => {
      csvData += chunk;
    });

    res.on('end', () => {
      console.log(`Download complete (${(csvData.length / 1024 / 1024).toFixed(2)} MB). Parsing stations...`);
      const lines = csvData.split(/\r?\n/);
      const stations = [];
      const seenIds = new Set();

      // Header line is index 0
      for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        if (!line || line.length < 10) continue;

        const parts = parseCSVLine(line);
        if (parts.length < 11) continue;

        const [usaf, wban, name, ctry, state, icao, latStr, lonStr, elevStr, begin, end] = parts;

        const lat = parseFloat(latStr);
        const lon = parseFloat(lonStr);

        // Validation: must have valid non-zero latitude & longitude in geo bounds
        if (
          isNaN(lat) ||
          isNaN(lon) ||
          lat < -90 ||
          lat > 90 ||
          lon < -180 ||
          lon > 180 ||
          (Math.abs(lat) < 0.001 && Math.abs(lon) < 0.001)
        ) {
          continue;
        }

        const id = `${usaf}-${wban}`;
        if (seenIds.has(id)) continue;
        seenIds.add(id);

        const cleanName = name || icao || id;
        const elev = elevStr ? parseFloat(elevStr) : null;

        stations.push({
          id,
          name: cleanName,
          lat: Math.round(lat * 1000) / 1000,
          lon: Math.round(lon * 1000) / 1000,
          country: ctry || '',
          state: state || '',
          icao: icao || '',
          usaf,
          wban,
          elev: isNaN(elev) ? undefined : Math.round(elev * 10) / 10,
        });
      }

      console.log(`Parsed ${stations.length} valid global weather stations.`);
      fs.writeFileSync(OUTPUT_FILE, JSON.stringify(stations));
      const fileSizeMb = (fs.statSync(OUTPUT_FILE).size / 1024 / 1024).toFixed(2);
      console.log(`Successfully saved station dataset to ${OUTPUT_FILE} (${fileSizeMb} MB).`);
    });
  })
  .on('error', (err) => {
    console.error('Download error:', err);
    process.exit(1);
  });
