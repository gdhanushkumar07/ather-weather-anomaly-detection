import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Plus, Minus, Globe, Satellite, Moon } from 'lucide-react';

import { WeatherLayerType } from '../types/weather';
import { setupStationLayers, setStationLayersVisibility, updateSelectedStationHalo } from './StationLayer';
import { VaneColormapLayer, GridFieldData } from './vane/ColormapLayer';
import { VaneParticlesLayer, WindGridData } from './vane/ParticlesLayer';
import { fetchWeatherGrid } from '../services/api';

interface AtherMapProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  selectedStationId: string | null;
  onSelectStation: (stationId: string) => void;
  activeLayers: Record<WeatherLayerType, boolean>;
  basemap: 'dark' | 'satellite';
  onToggleBasemap: (mode: 'dark' | 'satellite') => void;
}

export const AtherMap: React.FC<AtherMapProps> = ({
  stationsGeoJSON,
  selectedStationId,
  onSelectStation,
  activeLayers,
  basemap,
  onToggleBasemap
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  const colormapLayerRef = useRef<VaneColormapLayer | null>(null);
  const particlesLayerRef = useRef<VaneParticlesLayer | null>(null);

  const [isMapReady, setIsMapReady] = React.useState(false);
  const onSelectStationRef = useRef(onSelectStation);
  onSelectStationRef.current = onSelectStation;

  // 1. Initialize MapLibre with both Dark Canvas and Satellite Imagery Basemaps
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          esri_dark_base: {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'
            ],
            tileSize: 256,
            attribution: 'Tiles © Esri, DeLorme, NAVTEQ, OpenStreetMap'
          },
          esri_dark_ref: {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}'
            ],
            tileSize: 256
          },
          esri_sat_base: {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
            ],
            tileSize: 256,
            attribution: 'Source: Esri, Maxar, Earthstar Geographics'
          },
          esri_sat_ref: {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'
            ],
            tileSize: 256
          }
        },
        layers: [
          {
            id: 'esri-dark-gray-base',
            type: 'raster',
            source: 'esri_dark_base',
            minzoom: 0,
            maxzoom: 19,
            layout: { visibility: 'visible' }
          },
          {
            id: 'esri-dark-gray-reference',
            type: 'raster',
            source: 'esri_dark_ref',
            minzoom: 0,
            maxzoom: 19,
            layout: { visibility: 'visible' }
          },
          {
            id: 'esri-satellite-base',
            type: 'raster',
            source: 'esri_sat_base',
            minzoom: 0,
            maxzoom: 19,
            layout: { visibility: 'none' }
          },
          {
            id: 'esri-satellite-reference',
            type: 'raster',
            source: 'esri_sat_ref',
            minzoom: 0,
            maxzoom: 19,
            layout: { visibility: 'none' }
          }
        ]
      },
      center: [15, 20],
      zoom: 1.9,
      minZoom: 1.5,
      maxZoom: 18,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2)
    });

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

  // 4. Update Selected Station Halo
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;
    updateSelectedStationHalo(map, selectedStationId);
  }, [selectedStationId, isMapReady]);

  // 5. Vane Temperature WebGL Layer Toggle
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
            // Insert beneath reference overlay & stations
            const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : 'esri-dark-gray-reference';
            if (!map.getLayer(layer.id)) {
              map.addLayer(layer, beforeId);
            }
          })
          .catch((err) => console.error('Failed to load temperature field', err));
      } else {
        if (!map.getLayer(colormapLayerRef.current.id)) {
          const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : 'esri-light-gray-reference';
          map.addLayer(colormapLayerRef.current, beforeId);
        }
      }
    } else {
      if (colormapLayerRef.current && map.getLayer(colormapLayerRef.current.id)) {
        map.removeLayer(colormapLayerRef.current.id);
      }
    }
  }, [activeLayers.temperature, isMapReady]);

  // 6. Vane Wind WebGL Particle Layer Toggle
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
            const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : 'esri-dark-gray-reference';
            if (!map.getLayer(layer.id)) {
              map.addLayer(layer, beforeId);
            }
          })
          .catch((err) => console.error('Failed to load wind field', err));
      } else {
        if (!map.getLayer(particlesLayerRef.current.id)) {
          const beforeId = map.getLayer('ather-clusters') ? 'ather-clusters' : 'esri-light-gray-reference';
          map.addLayer(particlesLayerRef.current, beforeId);
        }
      }
    } else {
      if (particlesLayerRef.current && map.getLayer(particlesLayerRef.current.id)) {
        map.removeLayer(particlesLayerRef.current.id);
      }
    }
  }, [activeLayers.wind, isMapReady]);

  // Basemap switcher: Instant toggle between Dark Map and Satellite Imagery
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const isDark = basemap === 'dark';
    if (map.getLayer('esri-dark-gray-base')) {
      map.setLayoutProperty('esri-dark-gray-base', 'visibility', isDark ? 'visible' : 'none');
    }
    if (map.getLayer('esri-dark-gray-reference')) {
      map.setLayoutProperty('esri-dark-gray-reference', 'visibility', isDark ? 'visible' : 'none');
    }
    if (map.getLayer('esri-satellite-base')) {
      map.setLayoutProperty('esri-satellite-base', 'visibility', !isDark ? 'visible' : 'none');
    }
    if (map.getLayer('esri-satellite-reference')) {
      map.setLayoutProperty('esri-satellite-reference', 'visibility', !isDark ? 'visible' : 'none');
    }
  }, [basemap, isMapReady]);

  // 7. Fly to selected station
  useEffect(() => {
    if (!selectedStationId || !mapRef.current || !stationsGeoJSON) return;
    const feature = stationsGeoJSON.features.find((f) => f.properties?.id === selectedStationId);
    if (feature && feature.geometry.type === 'Point') {
      const [lon, lat] = feature.geometry.coordinates;
      mapRef.current.flyTo({
        center: [lon, lat],
        zoom: Math.max(mapRef.current.getZoom(), 8.0),
        duration: 1100,
        essential: true
      });
    }
  }, [selectedStationId, stationsGeoJSON]);

  const handleZoomIn = () => {
    mapRef.current?.zoomIn({ duration: 300 });
  };

  const handleZoomOut = () => {
    mapRef.current?.zoomOut({ duration: 300 });
  };

  const handleResetWorldView = () => {
    mapRef.current?.flyTo({
      center: [15, 20],
      zoom: 1.9,
      duration: 1200,
      essential: true
    });
  };

  return (
    <div className="map-viewport">
      <div ref={mapContainerRef} className="maplibre-container" />

      {/* Temperature Colormap Legend */}
      {activeLayers.temperature && (
        <div className="weather-legend">
          <div style={{ fontWeight: 600, color: '#f8fafc' }}>Surface Temperature (°C)</div>
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

      {/* Floating Minimal Map Navigation Controls */}
      <div className="floating-map-controls">
        <button
          className={`map-control-btn ${basemap === 'satellite' ? 'active-sat' : ''}`}
          onClick={() => onToggleBasemap(basemap === 'dark' ? 'satellite' : 'dark')}
          title={basemap === 'dark' ? 'Switch to Satellite Imagery' : 'Switch to Dark Map'}
        >
          {basemap === 'dark' ? <Satellite className="w-4 h-4 text-cyan-400" /> : <Moon className="w-4 h-4 text-amber-400" />}
        </button>
        <button className="map-control-btn" onClick={handleZoomIn} title="Zoom In">
          <Plus className="w-4 h-4" />
        </button>
        <button className="map-control-btn" onClick={handleZoomOut} title="Zoom Out">
          <Minus className="w-4 h-4" />
        </button>
        <button className="map-control-btn" onClick={handleResetWorldView} title="Reset to Full World View">
          <Globe className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
