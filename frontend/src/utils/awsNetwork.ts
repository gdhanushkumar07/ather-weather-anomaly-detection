/**
 * ATHER — Indian Automatic Weather Station (AWS) Network
 * Provides realistic geographical station network, 24-hour time-series generation,
 * interactive demo scenario injection, and real-time telemetry streaming simulation.
 */

import { AwsStation, AtherObservation, AtherDemoScenario } from '../types';
import { fuseAtherEvidence } from './atherEngine';

export interface StationDefinition {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  altitude: number;
  baseTemp: number;
  basePress: number;
  baseRh: number;
  baseWind: number;
}

export const INDIAN_AWS_DEFINITIONS: StationDefinition[] = [
  // Primary Metro & Regional Hubs
  { id: 'AWS-HYD-001', name: 'Hyderabad Central Met', state: 'Telangana', lat: 17.385, lon: 78.486, altitude: 542, baseTemp: 29.6, basePress: 1012.2, baseRh: 62, baseWind: 11 },
  { id: 'AWS-BOM-002', name: 'Mumbai Colaba Obs', state: 'Maharashtra', lat: 19.076, lon: 72.877, altitude: 14, baseTemp: 29.8, basePress: 1011.0, baseRh: 79, baseWind: 15 },
  { id: 'AWS-DEL-003', name: 'New Delhi Safdarjung', state: 'Delhi', lat: 28.613, lon: 77.209, altitude: 216, baseTemp: 31.2, basePress: 1008.5, baseRh: 49, baseWind: 9 },
  { id: 'AWS-BLR-004', name: 'Bengaluru Tech Park', state: 'Karnataka', lat: 12.971, lon: 77.594, altitude: 920, baseTemp: 25.4, basePress: 1014.2, baseRh: 66, baseWind: 12 },
  { id: 'AWS-MAA-005', name: 'Chennai Port Met', state: 'Tamil Nadu', lat: 13.082, lon: 80.270, altitude: 6, baseTemp: 30.2, basePress: 1010.8, baseRh: 76, baseWind: 13 },
  { id: 'AWS-CCU-006', name: 'Kolkata Alipore', state: 'West Bengal', lat: 22.572, lon: 88.363, altitude: 9, baseTemp: 31.0, basePress: 1009.4, baseRh: 81, baseWind: 8 },
  { id: 'AWS-AMD-007', name: 'Ahmedabad Sabarmati', state: 'Gujarat', lat: 23.022, lon: 72.571, altitude: 53, baseTemp: 33.5, basePress: 1007.8, baseRh: 44, baseWind: 10 },
  { id: 'AWS-PNQ-008', name: 'Pune Meteorological', state: 'Maharashtra', lat: 18.520, lon: 73.856, altitude: 560, baseTemp: 27.8, basePress: 1013.1, baseRh: 64, baseWind: 11 },
  { id: 'AWS-JAI-009', name: 'Jaipur Sanganer', state: 'Rajasthan', lat: 26.912, lon: 75.787, altitude: 431, baseTemp: 33.8, basePress: 1007.2, baseRh: 39, baseWind: 12 },
  { id: 'AWS-BBI-010', name: 'Bhubaneswar Coastal', state: 'Odisha', lat: 20.296, lon: 85.824, altitude: 45, baseTemp: 30.5, basePress: 1010.1, baseRh: 78, baseWind: 9 },
  { id: 'AWS-NAG-011', name: 'Nagpur Central Met', state: 'Maharashtra', lat: 21.145, lon: 79.088, altitude: 310, baseTemp: 31.8, basePress: 1009.9, baseRh: 54, baseWind: 9 },
  { id: 'AWS-LKO-012', name: 'Lucknow Amausi', state: 'Uttar Pradesh', lat: 26.846, lon: 80.946, altitude: 123, baseTemp: 30.8, basePress: 1008.9, baseRh: 58, baseWind: 7 },
  { id: 'AWS-PAT-013', name: 'Patna Airport AWS', state: 'Bihar', lat: 25.594, lon: 85.137, altitude: 53, baseTemp: 31.4, basePress: 1009.2, baseRh: 65, baseWind: 8 },
  { id: 'AWS-COK-014', name: 'Kochi Coastal Naval', state: 'Kerala', lat: 9.931, lon: 76.267, altitude: 4, baseTemp: 28.5, basePress: 1011.8, baseRh: 82, baseWind: 14 },
  { id: 'AWS-GAU-015', name: 'Guwahati Borjhar', state: 'Assam', lat: 26.144, lon: 91.736, altitude: 55, baseTemp: 28.2, basePress: 1010.4, baseRh: 84, baseWind: 6 },

  // Spatial Companion Stations (Essential for true Spatial k-NN analysis)
  { id: 'AWS-HYD-002', name: 'Secunderabad Begumpet', state: 'Telangana', lat: 17.452, lon: 78.468, altitude: 530, baseTemp: 29.8, basePress: 1012.1, baseRh: 63, baseWind: 10 },
  { id: 'AWS-NLG-025', name: 'Nalgonda Substation', state: 'Telangana', lat: 17.050, lon: 79.267, altitude: 240, baseTemp: 29.5, basePress: 1012.4, baseRh: 61, baseWind: 9 },
  { id: 'AWS-MBN-026', name: 'Mahbubnagar Regional', state: 'Telangana', lat: 16.748, lon: 78.003, altitude: 498, baseTemp: 29.9, basePress: 1012.0, baseRh: 60, baseWind: 11 },
  { id: 'AWS-WRG-016', name: 'Warangal Regional', state: 'Telangana', lat: 17.968, lon: 79.594, altitude: 270, baseTemp: 29.8, basePress: 1012.0, baseRh: 60, baseWind: 10 },
  { id: 'AWS-NZB-017', name: 'Nizamabad Met', state: 'Telangana', lat: 18.672, lon: 78.094, altitude: 395, baseTemp: 29.4, basePress: 1012.5, baseRh: 59, baseWind: 9 },
  { id: 'AWS-RMD-018', name: 'Ramagundam Industrial', state: 'Telangana', lat: 18.755, lon: 79.513, altitude: 179, baseTemp: 30.1, basePress: 1011.6, baseRh: 58, baseWind: 11 },
  { id: 'AWS-THA-019', name: 'Thane Regional AWS', state: 'Maharashtra', lat: 19.218, lon: 72.978, altitude: 18, baseTemp: 29.6, basePress: 1011.2, baseRh: 80, baseWind: 13 },
  { id: 'AWS-NVM-020', name: 'Navi Mumbai Hub', state: 'Maharashtra', lat: 19.033, lon: 73.029, altitude: 22, baseTemp: 29.7, basePress: 1011.1, baseRh: 78, baseWind: 14 },
  { id: 'AWS-NOI-021', name: 'Noida Substation', state: 'Uttar Pradesh', lat: 28.535, lon: 77.391, altitude: 200, baseTemp: 31.0, basePress: 1008.7, baseRh: 50, baseWind: 8 },
  { id: 'AWS-GGN-022', name: 'Gurugram Tech Hub', state: 'Haryana', lat: 28.459, lon: 77.026, altitude: 220, baseTemp: 31.1, basePress: 1008.6, baseRh: 49, baseWind: 9 },
  { id: 'AWS-BKN-023', name: 'Bikaner Thar AWS', state: 'Rajasthan', lat: 28.022, lon: 73.311, altitude: 242, baseTemp: 34.6, basePress: 1006.4, baseRh: 33, baseWind: 14 },
  { id: 'AWS-JDH-024', name: 'Jodhpur Desert Obs', state: 'Rajasthan', lat: 26.238, lon: 73.024, altitude: 231, baseTemp: 34.2, basePress: 1006.8, baseRh: 36, baseWind: 13 },
];

/**
 * Generates 24 hours of simulated realistic historical observations for a station
 */
export function generateStationHistory(
  def: StationDefinition,
  endTimeMs: number,
  scenario: AtherDemoScenario
): AtherObservation[] {
  const history: AtherObservation[] = [];
  const count = 24; // 24 hourly steps
  const stepMs = 3600 * 1000;

  for (let i = count - 1; i >= 0; i--) {
    const tMs = endTimeMs - i * stepMs;
    const hourOfDay = new Date(tMs).getHours();

    // Diurnal temperature oscillation: peak at 14:00 (+4°C), trough at 05:00 (-3.5°C)
    const diurnalT = Math.sin(((hourOfDay - 9) * Math.PI) / 12) * 3.8;
    // Diurnal humidity is inverse of temperature
    const diurnalRh = -diurnalT * 3.2;
    // Semidiurnal pressure tide (~1.5 hPa wave)
    const diurnalP = Math.cos((hourOfDay * Math.PI) / 6) * 1.2;

    const noiseT = (Math.sin(i * 1.7) + Math.cos(i * 0.9)) * 0.3;
    const noiseP = Math.sin(i * 1.3) * 0.2;
    const noiseRh = Math.cos(i * 1.1) * 1.5;

    let temp = Math.round((def.baseTemp + diurnalT + noiseT) * 10) / 10;
    let press = Math.round((def.basePress + diurnalP + noiseP) * 10) / 10;
    let rh = Math.round(Math.max(15, Math.min(95, def.baseRh + diurnalRh + noiseRh)));

    // Scenario-specific historical tweaks
    if (scenario === 'frozen_sensor' && def.id === 'AWS-DEL-003' && i <= 8) {
      // flatline last 8 hours
      temp = 30.4;
      press = 1012.0;
      rh = 52;
    } else if (scenario === 'sensor_drift' && def.id === 'AWS-BOM-002') {
      // gradual upward drift over 24 hours (+0.25°C per hour)
      const drift = (24 - i) * 0.22;
      temp = Math.round((temp + drift) * 10) / 10;
    }

    history.push({
      stationId: def.id,
      timestamp: tMs,
      isoTime: new Date(tMs).toISOString(),
      temperature: temp,
      pressure: press,
      humidity: rh,
      windSpeed: def.baseWind,
      isValid: true,
    });
  }

  return history;
}

/**
 * Creates full AWS station network with current readings & scenario injection
 */
export function buildAwsNetwork(
  scenario: AtherDemoScenario = 'normal',
  baseTimeMs: number = Date.now()
): AwsStation[] {
  // Step 1: Initialize all stations with normal historical series
  const stations: AwsStation[] = INDIAN_AWS_DEFINITIONS.map((def) => {
    const history = generateStationHistory(def, baseTimeMs, scenario);
    const last = history[history.length - 1];

    let currentObs: AtherObservation = {
      stationId: def.id,
      timestamp: baseTimeMs,
      isoTime: new Date(baseTimeMs).toISOString(),
      temperature: last.temperature,
      pressure: last.pressure,
      humidity: last.humidity,
      windSpeed: def.baseWind,
      isValid: true,
    };

    let healthPercent = 98.5;
    let healthStatus: 'healthy' | 'warning' | 'critical' | 'offline' = 'healthy';
    let healthTrend: 'stable' | 'degrading' | 'recovering' = 'stable';
    let maintenanceRisk: 'LOW' | 'MEDIUM' | 'HIGH' = 'LOW';
    let driftRate = 0.02;
    let consecutiveAnomalies = 0;

    // Step 2: Inject Scenario
    switch (scenario) {
      case 'hyd_spike':
        if (def.id === 'AWS-HYD-001') {
          // CANONICAL DEMO: Hyderabad reports 55.0°C, 1008.2 hPa, 91% RH
          currentObs.temperature = 55.0;
          currentObs.pressure = 1008.2;
          currentObs.humidity = 91;
          healthPercent = 64.0;
          healthStatus = 'warning';
          healthTrend = 'degrading';
          maintenanceRisk = 'HIGH';
          consecutiveAnomalies = 1;
        }
        break;

      case 'genuine_heatwave':
        // Regional heatwave scenario: coherent high temperatures across both Rajasthan and Telangana clusters
        if (def.id === 'AWS-HYD-001') {
          currentObs.temperature = 43.5;
          currentObs.humidity = 28;
          currentObs.pressure = 1007.8;
        } else if (def.id === 'AWS-HYD-002') {
          currentObs.temperature = 42.8;
          currentObs.humidity = 29;
          currentObs.pressure = 1008.0;
        } else if (def.id === 'AWS-WRG-016') {
          currentObs.temperature = 44.1;
          currentObs.humidity = 26;
          currentObs.pressure = 1007.5;
        } else if (def.id === 'AWS-NLG-025') {
          currentObs.temperature = 43.7;
          currentObs.humidity = 27;
          currentObs.pressure = 1007.6;
        } else if (def.id === 'AWS-MBN-026') {
          currentObs.temperature = 43.2;
          currentObs.humidity = 28;
          currentObs.pressure = 1007.9;
        } else if (def.id === 'AWS-JAI-009') {
          currentObs.temperature = 44.5;
          currentObs.humidity = 24;
        } else if (def.id === 'AWS-BKN-023') {
          currentObs.temperature = 45.2;
          currentObs.humidity = 22;
        } else if (def.id === 'AWS-JDH-024') {
          currentObs.temperature = 44.8;
          currentObs.humidity = 23;
        } else if (def.id === 'AWS-AMD-007') {
          currentObs.temperature = 43.4;
          currentObs.humidity = 28;
        }
        break;

      case 'frozen_sensor':
        if (def.id === 'AWS-DEL-003') {
          currentObs.temperature = 30.4;
          currentObs.pressure = 1012.0;
          currentObs.humidity = 52;
          healthPercent = 71.0;
          healthStatus = 'warning';
          healthTrend = 'degrading';
          maintenanceRisk = 'MEDIUM';
          consecutiveAnomalies = 4;
        }
        break;

      case 'sensor_drift':
        if (def.id === 'AWS-BOM-002') {
          currentObs.temperature = Math.round((def.baseTemp + 5.8) * 10) / 10;
          healthPercent = 62.0;
          healthStatus = 'warning';
          healthTrend = 'degrading';
          maintenanceRisk = 'HIGH';
          driftRate = 0.24;
          consecutiveAnomalies = 5;
        }
        break;

      case 'unphysical_combo':
        if (def.id === 'AWS-CCU-006') {
          currentObs.temperature = 52.0;
          currentObs.humidity = 96;
          currentObs.pressure = 1032.0;
          healthPercent = 58.0;
          healthStatus = 'warning';
          healthTrend = 'degrading';
          maintenanceRisk = 'HIGH';
          consecutiveAnomalies = 1;
        }
        break;
    }

    return {
      id: def.id,
      name: def.name,
      state: def.state,
      lat: def.lat,
      lon: def.lon,
      altitude: def.altitude,
      healthPercent,
      healthStatus,
      healthTrend,
      maintenanceRisk,
      consecutiveAnomalies,
      driftRateDegPerHour: driftRate,
      temp: currentObs.temperature,
      pressure: currentObs.pressure,
      windSpeed: currentObs.windSpeed || def.baseWind,
      humidity: currentObs.humidity,
      status: 'online',
      currentObs,
      history,
    };
  });

  // Step 3: Run ATHER 5-Layer Anomaly Engine + Evidence Fusion across the network!
  stations.forEach((st) => {
    st.latestAnalysis = fuseAtherEvidence(st, stations);
    if (st.latestAnalysis.severity === 'Critical') {
      st.healthStatus = 'critical';
    } else if (st.latestAnalysis.severity === 'Warning') {
      st.healthStatus = 'warning';
    }
  });

  return stations;
}

/**
 * Convenience helper to apply or switch demo scenario
 */
export function applyDemoScenario(
  _currentStations: AwsStation[],
  scenario: AtherDemoScenario
): AwsStation[] {
  return buildAwsNetwork(scenario);
}

/**
 * Simulates a single incoming real-time telemetry packet from a randomly selected station
 */
export function simulateIncomingPacket(
  stations: AwsStation[]
): { updatedNetwork: AwsStation[]; updatedStation: AwsStation } {
  const stepTime = Date.now();
  // Pick one station to receive an updated observation packet
  const targetIdx = Math.floor(Math.random() * stations.length);
  const target = stations[targetIdx];
  const def = INDIAN_AWS_DEFINITIONS.find((d) => d.id === target.id) || INDIAN_AWS_DEFINITIONS[0];

  const hourOfDay = new Date(stepTime).getHours();
  const diurnalT = Math.sin(((hourOfDay - 9) * Math.PI) / 12) * 3.8;
  const noiseT = (Math.random() - 0.5) * 0.4;
  const noiseP = (Math.random() - 0.5) * 0.3;
  const noiseRh = (Math.random() - 0.5) * 2.0;

  // If this station is currently under scenario fault (e.g. Hyderabad 55°C), keep the fault active
  let newTemp = target.temp;
  let newPress = target.pressure;
  let newRh = target.humidity;

  if (target.id === 'AWS-HYD-001' && target.latestAnalysis?.severity === 'Critical') {
    newTemp = Math.round((55.0 + (Math.random() - 0.5) * 0.2) * 10) / 10;
  } else if (target.id === 'AWS-DEL-003' && target.latestAnalysis?.anomalyType === 'Frozen Sensor') {
    newTemp = 30.4; // flatline
  } else {
    newTemp = Math.round((def.baseTemp + diurnalT + noiseT) * 10) / 10;
    newPress = Math.round((def.basePress + noiseP) * 10) / 10;
    newRh = Math.round(Math.max(15, Math.min(95, def.baseRh - diurnalT * 2.8 + noiseRh)));
  }

  const updatedObs: AtherObservation = {
    stationId: target.id,
    timestamp: stepTime,
    isoTime: new Date(stepTime).toISOString(),
    temperature: newTemp,
    pressure: newPress,
    humidity: newRh,
    windSpeed: target.windSpeed,
    isValid: true,
  };

  const updatedStation: AwsStation = {
    ...target,
    temp: newTemp,
    pressure: newPress,
    humidity: newRh,
    currentObs: updatedObs,
    history: [...(target.history || []).slice(-23), target.currentObs],
  };

  const updatedNetwork = stations.map((s, idx) => (idx === targetIdx ? updatedStation : s));

  // Re-run ATHER intelligence for this station
  updatedStation.latestAnalysis = fuseAtherEvidence(updatedStation, updatedNetwork);
  if (updatedStation.latestAnalysis.severity === 'Critical') {
    updatedStation.healthStatus = 'critical';
  } else if (updatedStation.latestAnalysis.severity === 'Warning') {
    updatedStation.healthStatus = 'warning';
  } else if (updatedStation.healthPercent >= 80) {
    updatedStation.healthStatus = 'healthy';
  }

  return {
    updatedNetwork,
    updatedStation,
  };
}

