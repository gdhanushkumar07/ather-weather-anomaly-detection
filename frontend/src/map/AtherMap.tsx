import React, { useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Plus, Minus, Globe, Satellite, Moon, Maximize } from 'lucide-react';

import { WeatherLayerType } from '../types/weather';
import {
  setupStationLayers,
  setStationLayersVisibility,
  updateSelectedStationHalo,
  updateNeighborConnections,
  clearNeighborConnections,
  setParameterLayer,
  ParameterField,
  setAnomalyOverlayVisibility
} from './StationLayer';
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

export interface MapViewState {
  center: [number, number];
  zoom: number;
  bearing: number;
  pitch: number;
}

export interface AtherMapHandle {
  /** Current camera view, or null if the map hasn't initialized yet. */
  getViewState: () => MapViewState | null;
  /** Immediately jumps to a previously captured view (no animation) — used
   * to restore exactly what the user was looking at before they navigated
   * away, undoing any fly-to-station that happened in between. */
  restoreViewState: (state: MapViewState) => void;
}

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
  showAnomalyOverlay?: boolean;
  /** Whether the Map workspace is the one currently visible. Used to skip
   * the fly-to-selected-station animation when nobody can see it (station
   * selected from another workspace), and to resize the map after it
   * becomes visible again (its container was display:none, which can leave
   * MapLibre's canvas at a stale size). Defaults to true so any other
   * caller of AtherMap keeps prior behavior. */
  isActive?: boolean;
}

export const AtherMap = forwardRef<AtherMapHandle, AtherMapProps>(({
  stationsGeoJSON,
  selectedStationId,
  onSelectStation,
  activeLayers,
  basemap,
  onToggleBasemap,
  isGlobeMode = false,
  onToggleGlobeMode,
  neighbors = [],
  showAnomalyOverlay = true,
  isActive = true
}, ref) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  const particlesLayerRef = useRef<VaneParticlesLayer | null>(null);

  const [isMapReady, setIsMapReady] = React.useState(false);
  const onSelectStationRef = useRef(onSelectStation);
  onSelectStationRef.current = onSelectStation;

  useImperativeHandle(ref, () => ({
    getViewState: () => {
      const map = mapRef.current;
      if (!map) return null;
      const c = map.getCenter();
      return { center: [c.lng, c.lat], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
    },
    restoreViewState: (state: MapViewState) => {
      mapRef.current?.jumpTo({ center: state.center, zoom: state.zoom, bearing: state.bearing, pitch: state.pitch });
    }
  }), []);

  // Always-current, non-reactive read of `isActive` for effects that must
  // NOT re-run just because visibility toggled (see the fly-to-station
  // effect below).
  const isActiveRef = useRef(isActive);
  isActiveRef.current = isActive;

  // Re-measure the map after its container becomes visible again — while
  // display:none, MapLibre may have last computed a stale/zero canvas size.
  const wasActiveRef = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActiveRef.current && mapRef.current) {
      mapRef.current.resize();
    }
    wasActiveRef.current = isActive;
  }, [isActive]);

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

  // 3a2. Anomaly overlay (Map Options): independent of the AWS markers
  // toggle, but re-synced whenever markers are toggled since turning
  // markers off forces the pulse halo off too (see setStationLayersVisibility).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;
    setAnomalyOverlayVisibility(map, activeLayers.stations && showAnomalyOverlay);
  }, [showAnomalyOverlay, activeLayers.stations, isMapReady]);

  // 3b. Real-data parameter halo (Phase 3 weather-layer fix): colors each
  // station by its ACTUAL reported temperature/pressure/humidity value.
  // Temperature/Pressure/Humidity are mutually exclusive in activeLayers
  // (see App.tsx), so at most one of these is ever active.
  const activeParameter: ParameterField | null = activeLayers.pressure
    ? 'pressure'
    : activeLayers.humidity
      ? 'humidity'
      : activeLayers.temperature
        ? 'temperature'
        : null;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;
    setParameterLayer(map, activeParameter);
  }, [activeParameter, isMapReady]);

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

  // NOTE: There used to be a "Vane Temperature WebGL Layer" here that fetched
  // a fully synthetic, procedurally generated global temperature field from
  // /api/weather/grid (see backend/app/weather/grid_service.py — a math
  // function of latitude/longitude only, with NO connection to any real AWS
  // observation) and painted it as a full-viewport WebGL raster. That is
  // exactly the "large cyan/colored tint that isn't actually data-driven"
  // bug reported against this feature. It has been permanently removed.
  // The ONLY temperature/pressure/humidity visualization now is the
  // real-station-data parameter halo wired in effect 3b above
  // (setParameterLayer, from StationLayer.ts), which is driven strictly by
  // each station's own reported value.

  // 6. Vane Wind WebGL Particle Layer Toggle (unchanged — wind is out of
  // scope for this fix and was not reported as broken).
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

  // 7. Fly to selected station — only when the map is actually the visible
  // workspace at the moment of selection (Phase 9/31 of the map-state-
  // persistence fix): flying while hidden has no visual purpose and would
  // silently change the view the user returns to after visiting Station
  // Intelligence. isActive is read via a ref, NOT a dependency — otherwise
  // this effect would re-fire (and fly again) every time the user comes
  // BACK to the map, since selectedStationId is intentionally left set so
  // the station stays highlighted.
  useEffect(() => {
    if (!isActiveRef.current || !selectedStationId || !mapRef.current || !stationsGeoJSON) return;
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

      {/* Phase 9: Active-Layer Indicator Badge */}
      <div className="active-layer-indicator-pill">
        <span className="active-layer-dot" />
        <div className="active-layer-text">
          <span className="layer-tag-label">ACTIVE LAYER: </span>
          <strong className="layer-param-name">
            {activeParameter === 'temperature'
              ? 'SURFACE TEMPERATURE · AWS OBSERVATIONS'
              : activeParameter === 'pressure'
                ? 'ATMOSPHERIC PRESSURE · AWS OBSERVATIONS'
                : activeParameter === 'humidity'
                  ? 'RELATIVE HUMIDITY · AWS OBSERVATIONS'
                  : activeLayers.wind
                    ? 'WIND PARTICLES · GFS / METEO VECTOR'
                    : `AWS NETWORK STATIONS · ${basemap === 'dark' ? 'DARK MAP' : 'SATELLITE'}`}
          </strong>
        </div>
      </div>

      {/* Phase 10: Dynamic Parameter Legend */}
      {activeParameter && (
        <div className="weather-legend">
          <div className="legend-header-row">
            <div className="legend-title-group">
              <span className="legend-primary-title">
                {activeParameter === 'temperature'
                  ? 'SURFACE TEMPERATURE'
                  : activeParameter === 'pressure'
                    ? 'ATMOSPHERIC PRESSURE'
                    : 'RELATIVE HUMIDITY'}
              </span>
              <span className="legend-unit-badge">
                {activeParameter === 'temperature' ? '°C' : activeParameter === 'pressure' ? 'hPa' : '%'}
              </span>
            </div>
            <span className="legend-source-tag">AWS IN-SITU / NWP REF</span>
          </div>

          {activeParameter === 'temperature' && (
            <>
              <div className="legend-bar temp-gradient" />
              <div className="legend-labels">
                <span>-30°</span><span>0°</span><span>+15°</span><span>+30°</span><span>+45°</span>
              </div>
            </>
          )}
          {activeParameter === 'pressure' && (
            <>
              <div className="legend-bar pressure-gradient" />
              <div className="legend-labels">
                <span>975</span><span>992</span><span>1013</span><span>1022</span><span>1035</span>
              </div>
            </>
          )}
          {activeParameter === 'humidity' && (
            <>
              <div className="legend-bar humidity-gradient" />
              <div className="legend-labels">
                <span>10%</span><span>30%</span><span>55%</span><span>75%</span><span>98%</span>
              </div>
            </>
          )}
          <div className="legend-provenance-note">
            Colored by each station's own reported value. Stations with active telemetry show AWS In-Situ;
            others show NWP model reference — see the station panel for exact provenance.
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
});
