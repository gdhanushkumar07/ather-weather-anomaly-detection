import React, { useEffect, useState, useRef } from 'react';
import L from 'leaflet';
import { fetchAtherStations } from '../../utils/api';
import type { AtherStationData, AIAnomalyItem } from '../../types/weather';

interface AIAnomalyLayerProps {
  map: L.Map | null;
  visible: boolean;
  onSelectStation: (station: AIAnomalyItem) => void;
}

export const AIAnomalyLayer: React.FC<AIAnomalyLayerProps> = ({
  map,
  visible,
  onSelectStation,
}) => {
  const [stations, setStations] = useState<AtherStationData[]>([]);
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    let isMounted = true;
    const loadData = async () => {
      try {
        const data = await fetchAtherStations();
        if (isMounted && data && data.stations) {
          setStations(data.stations);
        }
      } catch (err) {
        console.error('Failed to fetch stations for map:', err);
      }
    };

    loadData();
    const interval = window.setInterval(loadData, 10000);
    
    return () => {
      isMounted = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!map) return;

    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup().addTo(map);
    }

    const layerGroup = layerGroupRef.current;
    layerGroup.clearLayers();

    if (!visible) return;

    // 1. Draw Live API Stations (Green/Amber/Red)
    stations.forEach((station) => {
      const isAnomaly = station.anomaly?.is_anomaly;
      const confidence = station.anomaly?.confidence_score || 0;
      const isCritical = isAnomaly && confidence >= 0.8;

      const mappedStation = {
        id: station.station_id,
        stationName: station.name || station.station_id,
        state: '',
        lat: station.lat,
        lon: station.lon,
        severity: (isCritical ? 'D4' : isAnomaly ? 'D3' : 'D1') as any,
        severityLabel: isAnomaly ? 'Anomaly' : 'Healthy',
        status: (isCritical ? 'Critical' : isAnomaly ? 'Warning' : 'Active') as any,
        anomalyType: (station.anomaly?.root_cause || 'Sensor Drift') as any,
        confidenceScore: confidence,
        soilMoistureIndex: 0,
        heatAnomalyDelta: station.weather?.temperature_c || 0,
        rainfallDeficitPercent: 0,
        aiRecommendation: station.anomaly?.explanation || 'Operating normally.',
        lastUpdated: station.timestamp,
      } as AIAnomalyItem;

      let iconHtml = '';
      if (isCritical) {
        iconHtml = `
          <div class="relative flex items-center justify-center w-8 h-8 group cursor-pointer hover:scale-110 transition-transform">
            <div class="absolute w-full h-full rounded-full bg-red-500/50 animate-ping"></div>
            <div class="relative w-4 h-4 rounded-full bg-red-500 border-2 border-white shadow-[0_0_15px_rgba(239,68,68,1)]"></div>
          </div>
        `;
      } else if (isAnomaly) {
        iconHtml = `
          <div class="relative flex items-center justify-center w-6 h-6 group cursor-pointer hover:scale-110 transition-transform">
            <div class="absolute w-full h-full rounded-full bg-amber-500/50 animate-ping" style="animation-duration: 2s;"></div>
            <div class="relative w-3 h-3 rounded-full bg-amber-500 border-[1.5px] border-white shadow-[0_0_10px_rgba(245,158,11,1)]"></div>
          </div>
        `;
      } else {
        iconHtml = `
          <div class="relative flex items-center justify-center w-4 h-4 group cursor-pointer hover:scale-150 transition-transform">
            <div class="absolute w-full h-full rounded-full bg-emerald-500/20"></div>
            <div class="relative w-2 h-2 rounded-full bg-emerald-400 border border-white shadow-[0_0_8px_rgba(52,211,153,0.8)]"></div>
          </div>
        `;
      }

      const customIcon = L.divIcon({
        html: iconHtml,
        className: 'bg-transparent border-none',
        iconSize: isCritical ? [32, 32] : isAnomaly ? [24, 24] : [16, 16],
        iconAnchor: isCritical ? [16, 16] : isAnomaly ? [12, 12] : [8, 8],
      });

      const marker = L.marker([station.lat, station.lon], { icon: customIcon });

      // FIX: Stop event bubbling so the popup stays open!
      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        onSelectStation(mappedStation);
      });

      marker.bindTooltip(`
        <div class="px-2 py-1">
          <div class="text-xs font-bold uppercase tracking-wider text-slate-800">
            ${station.name || station.station_id}
          </div>
          <div class="text-[10px] font-bold ${isAnomaly ? 'text-red-600' : 'text-emerald-600'}">
            ${isAnomaly ? '⚠️ ANOMALY DETECTED' : '✓ SYSTEM HEALTHY'}
          </div>
        </div>
      `, { direction: 'top', offset: [0, -10], className: 'rounded-lg border-none shadow-xl bg-white/90 backdrop-blur-md' });

      marker.addTo(layerGroup);
    });

    // 2. Draw Static Blue Base Hubs (Major Cities)
    const majorCities = [
      { name: 'Mumbai', lat: 19.076, lon: 72.8777 },
      { name: 'Delhi', lat: 28.6139, lon: 77.209 },
      { name: 'Bengaluru', lat: 12.9716, lon: 77.5946 },
      { name: 'Hyderabad', lat: 17.385, lon: 78.4867 },
    ];

    majorCities.forEach(city => {
      const cityIcon = L.divIcon({
        html: `
          <div class="relative flex items-center justify-center w-6 h-6">
            <div class="absolute w-full h-full rounded-full bg-blue-500/40 animate-pulse"></div>
            <div class="relative w-2.5 h-2.5 rounded-full bg-blue-400 border-[1.5px] border-white shadow-[0_0_10px_rgba(59,130,246,0.8)]"></div>
          </div>
        `,
        className: 'bg-transparent border-none',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const cityMarker = L.marker([city.lat, city.lon], { icon: cityIcon });
      
      cityMarker.bindTooltip(`
        <div class="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-800">
          ${city.name} (Base Hub)
        </div>
      `, { direction: 'top', offset: [0, -8], className: 'rounded-lg border-none shadow-xl bg-white/90 backdrop-blur-md' });

      cityMarker.addTo(layerGroup);
    });

  }, [map, visible, stations, onSelectStation]);

  return null; 
};