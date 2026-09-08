import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { WeatherLayerType } from '../types/weather';
import { setupStationLayers, setStationLayersVisibility } from './StationLayer';
import { VaneColormapLayer, GridFieldData } from './vane/ColormapLayer';
import { VaneParticlesLayer, WindGridData } from './vane/ParticlesLayer';
import { fetchWeatherGrid } from '../services/api';

interface AtherMapProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  selectedStationId: string | null;
  onSelectStation: (stationId: string) => void;
  activeLayers: Record<WeatherLayerType, boolean>;
}

export const AtherMap: React.FC<AtherMapProps> = ({
  stationsGeoJSON,
  selectedStationId,
  onSelectStation,
  activeLayers
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  const colormapLayerRef = useRef<VaneColormapLayer | null>(null);
  const particlesLayerRef = useRef<VaneParticlesLayer | null>(null);

  const [isMapReady, setIsMapReady] = React.useState(false);
  const onSelectStationRef = useRef(onSelectStation);
  onSelectStationRef.current = onSelectStation;

  // 1. Initialize MapLibre
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          carto_light: {
            type: 'raster',
            tiles: [
              'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
              'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
              'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png'
            ],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors, © CARTO'
          }
        },
        layers: [
          {
            id: 'carto-light-basemap',
            type: 'raster',
            source: 'carto_light',
            minzoom: 0,
            maxzoom: 19
          }
        ]
      },
      center: [20, 20],
      zoom: 2.2,
      minZoom: 1.5,
      maxZoom: 18,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2)
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

    map.on('load', () => {
      mapRef.current = map;
      setIsMapReady(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      setIsMapReady(false);
    };
  }, []);

  // 2. Update stations when GeoJSON loads or changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady || !stationsGeoJSON) return;
    setupStationLayers(map, stationsGeoJSON, (id) => onSelectStationRef.current(id));
  }, [stationsGeoJSON, isMapReady]);

  // 3. Station layer visibility toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;
    setStationLayersVisibility(map, activeLayers.stations);
  }, [activeLayers.stations, isMapReady]);

  // 4. Vane Temperature WebGL Layer Toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    if (activeLayers.temperature) {
      if (!colormapLayerRef.current) {
        fetchWeatherGrid('temperature')
          .then((grid: GridFieldData) => {
            if (!mapRef.current) return;
            const layer = new VaneColormapLayer(grid);
            colormapLayerRef.current = layer;
            // Insert under stations if station layer exists
            const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : undefined;
            if (!map.getLayer(layer.id)) {
              map.addLayer(layer, beforeId);
            }
          })
          .catch((err) => console.error('Failed to load temperature field', err));
      } else {
        if (!map.getLayer(colormapLayerRef.current.id)) {
          const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : undefined;
          map.addLayer(colormapLayerRef.current, beforeId);
        }
      }
    } else {
      if (colormapLayerRef.current && map.getLayer(colormapLayerRef.current.id)) {
        map.removeLayer(colormapLayerRef.current.id);
      }
    }
  }, [activeLayers.temperature, isMapReady]);

  // 5. Vane Wind WebGL Particle Layer Toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    if (activeLayers.wind) {
      if (!particlesLayerRef.current) {
        fetchWeatherGrid('wind')
          .then((grid: WindGridData) => {
            if (!mapRef.current) return;
            const layer = new VaneParticlesLayer(grid);
            particlesLayerRef.current = layer;
            const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : undefined;
            if (!map.getLayer(layer.id)) {
              map.addLayer(layer, beforeId);
            }
          })
          .catch((err) => console.error('Failed to load wind field', err));
      } else {
        if (!map.getLayer(particlesLayerRef.current.id)) {
          const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : undefined;
          map.addLayer(particlesLayerRef.current, beforeId);
        }
      }
    } else {
      if (particlesLayerRef.current && map.getLayer(particlesLayerRef.current.id)) {
        map.removeLayer(particlesLayerRef.current.id);
      }
    }
  }, [activeLayers.wind, isMapReady]);

  // 6. Fly to selected station
  useEffect(() => {
    if (!selectedStationId || !mapRef.current || !stationsGeoJSON) return;
    const feature = stationsGeoJSON.features.find((f) => f.properties?.id === selectedStationId);
    if (feature && feature.geometry.type === 'Point') {
      const [lon, lat] = feature.geometry.coordinates;
      mapRef.current.flyTo({
        center: [lon, lat],
        zoom: Math.max(mapRef.current.getZoom(), 8.5),
        duration: 1200,
        essential: true
      });
    }
  }, [selectedStationId, stationsGeoJSON]);

  return (
    <div className="map-viewport">
      <div ref={mapContainerRef} className="maplibre-container" />

      {/* Temperature Colormap Legend */}
      {activeLayers.temperature && (
        <div className="weather-legend">
          <div style={{ fontWeight: 600, color: '#0f172a' }}>Surface Temperature (°C)</div>
          <div className="legend-bar temp-gradient" />
          <div className="legend-labels">
            <span>-30°</span>
            <span>0°</span>
            <span>+15°</span>
            <span>+30°</span>
            <span>+45°</span>
          </div>
        </div>
      )}
    </div>
  );
};
