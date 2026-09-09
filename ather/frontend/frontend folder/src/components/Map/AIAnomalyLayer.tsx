import React, { useEffect, useState, useRef, useCallback } from 'react';
import type { Map as LeafletMap } from 'leaflet';
import L from 'leaflet';
import type { AtherStationData } from '../../types/weather';
import { fetchAtherStations } from '../../utils/api';

interface AIAnomalyLayerProps {
  map: LeafletMap | null;
  visible: boolean;
  onSelectStation: (station: any) => void;
}

/** Map ATHER severity_score to visual styling */
function getSeverityStyle(station: AtherStationData) {
  const { is_anomaly, severity_score, sensor_health_index } = station.anomaly;

  if (!is_anomaly) {
    return {
      color: '#22c55e',       // green-500
      border: '#16a34a',      // green-600
      bgPulse: '',
      label: '✓',
      statusText: 'Normal',
    };
  }

  if (severity_score > 0.7) {
    return {
      color: '#ef4444',       // red-500
      border: '#dc2626',      // red-600
      bgPulse: 'bg-red-500/40',
      label: '!',
      statusText: 'Critical',
    };
  }

  if (severity_score > 0.4) {
    return {
      color: '#f97316',       // orange-500
      border: '#ea580c',      // orange-600
      bgPulse: 'bg-orange-500/30',
      label: '⚠',
      statusText: 'Severe',
    };
  }

  return {
    color: '#eab308',         // yellow-500
    border: '#ca8a04',        // yellow-600
    bgPulse: '',
    label: '~',
    statusText: 'Moderate',
  };
}

const REFRESH_INTERVAL_MS = 60_000; // 60 seconds

export const AIAnomalyLayer: React.FC<AIAnomalyLayerProps> = ({
  map,
  visible,
  onSelectStation,
}) => {
  const [stations, setStations] = useState<AtherStationData[]>([]);
  const [atherStatus, setAtherStatus] = useState<string>('loading');
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStations = useCallback(async () => {
    try {
      const data = await fetchAtherStations();
      setStations(data.stations || []);
      setAtherStatus(data.status || 'offline');
    } catch (err) {
      console.warn('Could not load ATHER station data:', err);
      setAtherStatus('error');
    }
  }, []);

  // Initial load + auto-refresh
  useEffect(() => {
    loadStations();

    intervalRef.current = setInterval(loadStations, REFRESH_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [loadStations]);

  // Render markers
  useEffect(() => {
    if (!map) return;

    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup().addTo(map);
    }

    const lg = layerGroupRef.current;
    lg.clearLayers();

    if (!visible) return;

    stations.forEach((st) => {
      const style = getSeverityStyle(st);
      const tempStr = `${st.weather.temperature_c.toFixed(1)}°C`;
      const isAnomaly = st.anomaly.is_anomaly;

      const iconHtml = `
        <div class="relative flex items-center justify-center cursor-pointer group">
          ${
            isAnomaly && style.bgPulse
              ? `<div class="absolute w-8 h-8 rounded-full ${style.bgPulse} animate-ping"></div>`
              : ''
          }
          <div 
            style="background: ${style.color}; border-color: ${style.border};"
            class="relative w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shadow-lg border-2 transform transition-transform group-hover:scale-125"
          >
            ${style.label}
          </div>
          <div class="absolute -top-8 px-2 py-0.5 rounded bg-slate-900/90 text-white text-[10px] font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none border border-white/10 shadow-md">
            ${st.name} · ${tempStr} · ${style.statusText}
          </div>
        </div>
      `;

      const markerIcon = L.divIcon({
        html: iconHtml,
        className: 'ather-station-marker',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const marker = L.marker([st.lat, st.lon], { icon: markerIcon });
      marker.on('click', () => {
        // Convert to AIAnomalyItem-compatible format for CompactWeatherOverlay
        onSelectStation({
          id: st.station_id,
          stationName: st.name,
          state: 'India',
          lat: st.lat,
          lon: st.lon,
          severity: st.anomaly.is_anomaly
            ? (st.anomaly.severity_score > 0.7 ? 'D3' : st.anomaly.severity_score > 0.4 ? 'D2' : 'D1')
            : 'D0',
          severityLabel: st.anomaly.root_cause,
          status: style.statusText as any,
          anomalyType: st.anomaly.root_cause,
          confidenceScore: Math.round(st.anomaly.confidence_score * 1000) / 10,
          soilMoistureIndex: 50,
          heatAnomalyDelta: 0,
          rainfallDeficitPercent: 0,
          aiRecommendation: st.anomaly.explanation,
          lastUpdated: new Date(st.timestamp).toLocaleTimeString(),
          // Pass full ATHER data for the overlay
          atherData: st,
        });
      });

      marker.addTo(lg);
    });

    return () => {
      lg.clearLayers();
    };
  }, [map, visible, stations, onSelectStation]);

  return null;
};

