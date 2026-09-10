import React, { useEffect, useRef, useCallback } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Plus, Minus, Globe, Satellite, Moon, Maximize } from 'lucide-react';

import { WeatherLayerType } from '../types/weather';
import {
  setupStationLayers,
  setStationLayersVisibility,
  updateSelectedStationHalo,
  updateNeighborConnections,
  clearNeighborConnections
} from './StationLayer';
import { VaneColormapLayer, GridFieldData } from './vane/ColormapLayer';
import { VaneParticlesLayer, WindGridData } from './vane/ParticlesLayer';
import { fetchWeatherGrid } from '../services/api';
import { AWSNeighbor } from '../aws/awsGeo';
import { AWSStationOverlay } from '../aws/AWSStationOverlay';

// Matches --bg-app in index.css, so any not-yet-loaded tile area (network
// latency during pan/zoom) shows a seamless dark fill instead of a black gap.
const MAP_BACKGROUND_COLOR = '#080c14';

// Same "close enough to fly to a single station" zoom level already used by
// the existing "fly to selected station" effect below -- reused here so the
// 3D AWS model appears exactly when the map itself considers you at
// station-level zoom, not an arbitrarily different threshold.
const AWS_MODEL_ZOOM_THRESHOLD = 8.0;

interface AtherMapProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  selectedStationId: string | null;
  onSelectStation: (stationId: string) => void;
  activeLayers: Record<WeatherLayerType, boolean>;
  basemap: 'dark' | 'satellite';
  onToggleBasemap: (mode: 'dark' | 'satellite') => void;
  isGlobeMode?: boolean;
  onToggleGlobeMode?: () => void;
  neighbors?: AWSNeighbor[];
}

export const AtherMap: React.FC<AtherMapProps> = ({
  stationsGeoJSON,
  selectedStationId,
  onSelectStation,
  activeLayers,
  basemap,
  onToggleBasemap,
  isGlobeMode = false,
  onToggleGlobeMode,
  neighbors = []
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
        // Globe projection is set once, here, and never toggled again.
        // MapLibre's own renderer automatically and smoothly blends globe
        // rendering into flat mercator as the user zooms in (see
        // GlobeTransform's built-in `_globeness` interpolation) -- forcing a
        // manual setProjection() switch at a fixed zoom breakpoint fights
        // against that built-in transition and was the actual cause of the
        // stutter/sudden-switch/seam artifacts during zoom.
        projection: { type: 'globe' },
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
            // Renders beneath everything else. Without this, any screen
            // area whose raster tile hasn't finished loading yet (network
            // latency during fast pan/zoom) shows the canvas's own clear
            // color -- effectively a black gap/flash. A solid fill matching
            // the app's own background makes that moment invisible instead.
            id: 'ather-map-background',
            type: 'background',
            paint: { 'background-color': MAP_BACKGROUND_COLOR }
          },
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

  // 2c. Fly to World 3D Globe when globe mode is toggled
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    if (isGlobeMode) {
      map.flyTo({
        center: [15, 20],
        zoom: 1.8,
        duration: 1200,
        essential: true
      });
    }
  }, [isGlobeMode, isMapReady]);

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

  // 4b. Three-neighbor validation connection lines + highlight markers.
  // Native MapLibre line/circle layers -- geo-attachment during pan/zoom/
  // rotate is handled by the map itself (see StationLayer.ts), same as
  // every other station layer.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    if (!selectedStationId || neighbors.length === 0 || !stationsGeoJSON) {
      clearNeighborConnections(map);
      return;
    }
    const primaryFeature = stationsGeoJSON.features.find((f) => f.properties?.id === selectedStationId);
    if (!primaryFeature || primaryFeature.geometry.type !== 'Point') {
      clearNeighborConnections(map);
      return;
    }
    const [pLng, pLat] = primaryFeature.geometry.coordinates;
    updateNeighborConnections(
      map,
      { lng: pLng, lat: pLat },
      neighbors.map((n) => ({ lng: n.lng, lat: n.lat }))
    );
  }, [selectedStationId, neighbors, stationsGeoJSON, isMapReady]);

  // 4c. Track whether we're at close/station-level zoom, for gating the 3D
  // AWS model overlay. A boolean, updated only when it actually crosses the
  // threshold -- not on every zoom tick -- to avoid re-rendering on every
  // scroll frame.
  const [isCloseZoom, setIsCloseZoom] = React.useState(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const checkZoom = () => {
      const close = map.getZoom() >= AWS_MODEL_ZOOM_THRESHOLD;
      setIsCloseZoom((prev) => (prev !== close ? close : prev));
    };
    checkZoom();
    map.on('zoom', checkZoom);
    return () => {
      map.off('zoom', checkZoom);
    };
  }, [isMapReady]);

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

  const handleZoomIn = useCallback(() => {
    mapRef.current?.zoomIn({ duration: 300 });
  }, []);

  const handleZoomOut = useCallback(() => {
    mapRef.current?.zoomOut({ duration: 300 });
  }, []);

  const handleResetWorldView = useCallback(() => {
    mapRef.current?.flyTo({
      center: [15, 20],
      zoom: 1.9,
      duration: 1200,
      essential: true
    });
  }, []);

  // Selected station's real coordinates/status, for the 3D AWS overlay.
  // Recomputed only when the selection or the underlying data actually
  // changes -- not on every render.
  const selectedFeature = React.useMemo(() => {
    if (!selectedStationId || !stationsGeoJSON) return null;
    const f = stationsGeoJSON.features.find((feat) => feat.properties?.id === selectedStationId);
    if (!f || f.geometry.type !== 'Point') return null;
    const [lng, lat] = f.geometry.coordinates;
    return { lng, lat, status: f.properties?.status || 'NORMAL', name: f.properties?.name || selectedStationId };
  }, [selectedStationId, stationsGeoJSON]);

  return (
    <div className="map-viewport">
      <div ref={mapContainerRef} className="maplibre-container" />

      {/* Realistic 3D AWS model -- only the selected station, only at close
          zoom. At most one 3D scene ever exists at a time. */}
      {isMapReady && mapRef.current && isCloseZoom && selectedFeature && (
        <AWSStationOverlay
          map={mapRef.current}
          stationId={selectedStationId as string}
          stationName={selectedFeature.name}
          lng={selectedFeature.lng}
          lat={selectedFeature.lat}
          status={selectedFeature.status}
        />
      )}

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
        <div className="map-zoom-group">
          <button className="map-control-btn zoom-btn top" onClick={handleZoomIn} title="Zoom In">
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button className="map-control-btn zoom-btn bottom" onClick={handleZoomOut} title="Zoom Out">
            <Minus className="w-3.5 h-3.5" />
          </button>
        </div>

        <button
          className={`map-control-btn ${isGlobeMode ? 'active-sat' : ''}`}
          onClick={onToggleGlobeMode || handleResetWorldView}
          title={isGlobeMode ? "Exit 3D Globe to 2D Map" : "Open 3D Satellite Earth Globe"}
        >
          <Globe className={`w-3.5 h-3.5 ${isGlobeMode ? 'text-amber-400' : 'text-cyan-400'}`} />
        </button>

        <button
          className={`map-control-btn ${basemap === 'satellite' ? 'active-sat' : ''}`}
          onClick={() => onToggleBasemap(basemap === 'dark' ? 'satellite' : 'dark')}
          title={basemap === 'dark' ? 'Switch to Satellite Imagery' : 'Switch to Dark Map'}
        >
          {basemap === 'dark' ? <Satellite className="w-3.5 h-3.5 text-cyan-400" /> : <Moon className="w-3.5 h-3.5 text-amber-400" />}
        </button>

        <button
          className="map-control-btn"
          onClick={() => {
            if (!document.fullscreenElement) {
              document.documentElement.requestFullscreen().catch(() => {});
            } else {
              document.exitFullscreen().catch(() => {});
            }
          }}
          title="Toggle Fullscreen"
        >
          <Maximize className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};
