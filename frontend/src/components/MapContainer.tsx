import React, { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { 
  WeatherLayer, 
  LocationCoords, 
  WindSpeedUnit, 
  TempUnit, 
  PressureUnit, 
  MapBasemap, 
  WebcamItem, 
  AltitudeLevel, 
  StationType,
  AwsStation,
  AnomalyMarker,
  AtherMapMode,
  GlobalWeatherStation
} from '../types';
import Supercluster from 'supercluster';
import { WindParticleEngine } from './WindParticleEngine';
import { HeatmapCanvasLayer } from './HeatmapCanvasLayer';
import { WindLabelsLayer } from './WindLabelsLayer';
import { computeWindVector } from '../utils/windMath';
import { buildAwsNetwork } from '../utils/awsNetwork';
import { calculateHaversineDistance } from '../utils/atherEngine';
import { getGlobalGridCells, getOpenMeteoRequestCount } from '../services/stationService';

const DEFAULT_AWS_STATIONS: AwsStation[] = buildAwsNetwork('hyd_spike');

const AI_ANOMALIES: AnomalyMarker[] = [
  {
    id: 'ANOM-BAY-01',
    title: 'Severe Convective Cyclone Vortex',
    level: 'D5',
    lat: 16.5,
    lon: 86.8,
    riskScore: 96,
    category: 'wind',
    desc: 'Rapid barometric fall (-14 hPa/3h) with cyclonic vorticity exceeding 120 kt.',
  },
  {
    id: 'ANOM-THAR-02',
    title: 'Extreme Heatwave Thermal Gradient',
    level: 'D3',
    lat: 27.8,
    lon: 72.4,
    riskScore: 78,
    category: 'temperature',
    desc: 'Surface thermal anomaly +5.8°C above 30-year climatological normal.',
  },
  {
    id: 'ANOM-ARAB-03',
    title: 'Sub-tropical Low Pressure Depletion',
    level: 'D4',
    lat: 15.8,
    lon: 64.2,
    riskScore: 88,
    category: 'pressure',
    desc: 'Deep marine depression with central pressure drop to 992 hPa.',
  },
  {
    id: 'ANOM-MEGH-04',
    title: 'Extreme Flash Rain Gradient',
    level: 'D4',
    lat: 25.4,
    lon: 91.8,
    riskScore: 84,
    category: 'precipitation',
    desc: 'Orographic precipitation plume detected, localized flux > 48 mm/h.',
  },
];

interface MapContainerProps {
  activeLayer: WeatherLayer;
  timeOffsetHours: number;
  selectedLocation: LocationCoords | null;
  onSelectLocation: (coords: LocationCoords) => void;
  windUnit: WindSpeedUnit;
  tempUnit: TempUnit;
  pressureUnit: PressureUnit;
  showWebcams: boolean;
  webcams: WebcamItem[];
  onSelectWebcam: (webcam: WebcamItem) => void;
  basemap: MapBasemap;
  particleDensity: number;
  altitudeLevel: AltitudeLevel;
  showParticles: boolean;
  showPressureIsolines: boolean;
  is3D: boolean;
  stationType: StationType | null;
  mapRef?: React.MutableRefObject<L.Map | null>;
  showAwsStations?: boolean;
  showAnomalyMarkers?: boolean;
  awsStations?: AwsStation[];
  selectedStation?: AwsStation | null;
  onSelectStation?: (station: AwsStation) => void;
  mapMode?: AtherMapMode;
  showGlobalStations?: boolean;
  globalStations?: GlobalWeatherStation[];
  selectedGlobalStation?: GlobalWeatherStation | null;
  onSelectGlobalStation?: (station: GlobalWeatherStation) => void;
}

export const MapContainer: React.FC<MapContainerProps> = ({
  activeLayer,
  timeOffsetHours,
  selectedLocation,
  onSelectLocation,
  windUnit,
  tempUnit,
  pressureUnit,
  showWebcams,
  webcams,
  onSelectWebcam,
  basemap,
  particleDensity,
  altitudeLevel,
  showParticles,
  showPressureIsolines,
  is3D,
  stationType,
  mapRef,
  showAwsStations = true,
  showAnomalyMarkers = true,
  awsStations,
  selectedStation,
  onSelectStation,
  mapMode = 'monitoring',
  showGlobalStations = true,
  globalStations = [],
  selectedGlobalStation,
  onSelectGlobalStation,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const particleCanvasRef = useRef<HTMLCanvasElement>(null);
  const heatmapCanvasRef = useRef<HTMLCanvasElement>(null);
  const labelsCanvasRef = useRef<HTMLCanvasElement>(null);

  const tileLayerRef = useRef<L.TileLayer | null>(null);
  const referenceLayerRef = useRef<L.TileLayer | null>(null);
  const satelliteTileLayerRef = useRef<L.TileLayer | null>(null);
  const radarTileLayerRef = useRef<L.TileLayer | null>(null);
  const particleEngineRef = useRef<WindParticleEngine | null>(null);
  const heatmapEngineRef = useRef<HeatmapCanvasLayer | null>(null);
  const labelsEngineRef = useRef<WindLabelsLayer | null>(null);
  const pickerMarkerRef = useRef<L.Marker | null>(null);
  const webcamLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const stationLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const awsLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const anomalyLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const spatialLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const superclusterRef = useRef<Supercluster | null>(null);
  const renderClustersRef = useRef<(() => void) | null>(null);
  const canvasRendererRef = useRef<L.Canvas | null>(null);
  const activeStationLayersRef = useRef<Map<string, L.Layer>>(new Map());

  // Performance HUD state for developer performance verification
  const [perfStats, setPerfStats] = useState({
    totalStations: 0,
    level: 'Level 1: World Grid Aggregation',
    visibleCount: 0,
    clustersCount: 0,
    individualCount: 0,
    zoom: 2.2,
    renderTimeMs: 0,
    openMeteoReqs: 0,
  });

  // Picker tool state (shows wind & temp at point)
  const [pickerData, setPickerData] = useState<{
    lat: number;
    lon: number;
    speedKnots: number;
    speedKmh: number;
    dirDeg: number;
    temp: number;
  } | null>(null);

  const isFirstMountRef = useRef(true);

  // 1. Initialize Map
  useEffect(() => {
    const container = mapContainerRef.current;
    if (!container) return;

    // Prevent "Map container is already initialized" error
    if (mapInstanceRef.current) {
      try {
        mapInstanceRef.current.remove();
      } catch (e) {
        console.warn('Map cleanup warning:', e);
      }
      mapInstanceRef.current = null;
    }
    if ((container as any)._leaflet_id) {
      delete (container as any)._leaflet_id;
    }

    // Global 2D World Map on initial load - showing all continents and countries
    const map = L.map(container, {
      center: [20, 0],
      zoom: 2.5,
      minZoom: 2,
      maxZoom: 18,
      zoomControl: false,
      attributionControl: false,
      worldCopyJump: true,
      preferCanvas: true,
    });

    mapInstanceRef.current = map;
    if (mapRef) {
      mapRef.current = map;
    }

    // Initialize Tile Layer using Option C (Esri World_Dark_Gray_Base) - 100% keyless, no watermark
    const tileUrl = getBasemapUrl(basemap);
    const tileLayer = L.tileLayer(tileUrl, {
      attribution: 'Tiles © Esri',
      maxZoom: 16,
    }).addTo(map);
    tileLayerRef.current = tileLayer;

    // Add Esri dark reference layer for country boundaries and city labels
    if (basemap === 'dark') {
      const refLayer = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
        {
          attribution: 'Tiles © Esri',
          maxZoom: 16,
        }
      ).addTo(map);
      referenceLayerRef.current = refLayer;
    }

    // Force size calculation to ensure tiles load immediately
    map.whenReady(() => {
      map.invalidateSize();
    });
    const sizeTimer = setTimeout(() => {
      map.invalidateSize();
    }, 100);

    // Initialize Canvas Renderer for ultra-low CPU station dots (zero DOM elements)
    canvasRendererRef.current = L.canvas({ padding: 0.5 });

    // Initialize Layer Groups
    webcamLayerGroupRef.current = L.layerGroup().addTo(map);
    stationLayerGroupRef.current = L.layerGroup().addTo(map);
    awsLayerGroupRef.current = L.layerGroup().addTo(map);
    anomalyLayerGroupRef.current = L.layerGroup().addTo(map);
    spatialLayerGroupRef.current = L.layerGroup().addTo(map);

    // Initialize Engines
    if (heatmapCanvasRef.current) {
      const heatmapEngine = new HeatmapCanvasLayer(map, heatmapCanvasRef.current);
      heatmapEngineRef.current = heatmapEngine;
      heatmapEngine.setLayer(activeLayer);
      heatmapEngine.setTimeOffset(timeOffsetHours);
      heatmapEngine.setAltitudeLevel(altitudeLevel);
      heatmapEngine.setShowPressureIsolines(showPressureIsolines);
    }

    if (particleCanvasRef.current) {
      const particleEngine = new WindParticleEngine(map, particleCanvasRef.current);
      particleEngineRef.current = particleEngine;
      particleEngine.setTimeOffset(timeOffsetHours);
      particleEngine.setDensity(particleDensity);
      particleEngine.setAltitudeLevel(altitudeLevel);
      // Strictly only start if activeLayer is wind
      if (activeLayer === 'wind' && showParticles) {
        particleEngine.start();
      }
    }

    if (labelsCanvasRef.current) {
      const labelsEngine = new WindLabelsLayer(map, labelsCanvasRef.current);
      labelsEngineRef.current = labelsEngine;
      labelsEngine.setTimeOffset(timeOffsetHours);
      labelsEngine.setAltitudeLevel(altitudeLevel);
      labelsEngine.setWindUnit(windUnit);
      labelsEngine.setTempUnit(tempUnit);
      if (activeLayer === 'wind') {
        labelsEngine.setMode('wind');
      } else if (activeLayer === 'temperature') {
        labelsEngine.setMode('temperature');
      } else {
        labelsEngine.setMode('none');
      }
    }

    // Debounced moveend / zoomend handlers — NEVER run expensive station or canvas loops during active drag ('move')
    let moveTimer: any = null;
    const onMoveOrZoomEnd = () => {
      clearTimeout(moveTimer);
      moveTimer = setTimeout(() => {
        heatmapEngineRef.current?.resize();
        if (showParticles) {
          particleEngineRef.current?.resize();
        }
        labelsEngineRef.current?.resize();
        renderClustersRef.current?.();
      }, 100);
    };

    map.on('moveend', onMoveOrZoomEnd);
    map.on('zoomend', onMoveOrZoomEnd);
    map.on('resize', onMoveOrZoomEnd);

    // Map click handler to drop ATHER Meteorological Picker
    map.on('click', (e: L.LeafletMouseEvent) => {
      const lat = e.latlng.lat;
      const lon = e.latlng.lng;

      const vector = computeWindVector(lat, lon, timeOffsetHours, altitudeLevel);
      const radLat = (lat * Math.PI) / 180;
      const approxTemp = Math.round(30 * Math.cos(radLat * 1.1) + 2);

      setPickerData({
        lat,
        lon,
        speedKnots: vector.speedKnots,
        speedKmh: Math.round(vector.speed),
        dirDeg: vector.dirDeg,
        temp: approxTemp,
      });

      onSelectLocation({ lat, lon });
    });

    return () => {
      clearTimeout(sizeTimer);
      particleEngineRef.current?.stop();
      if (satelliteTileLayerRef.current) {
        try {
          satelliteTileLayerRef.current.remove();
        } catch (e) {
          // ignore
        }
        satelliteTileLayerRef.current = null;
      }
      if (radarTileLayerRef.current) {
        try {
          radarTileLayerRef.current.remove();
        } catch (e) {
          // ignore
        }
        radarTileLayerRef.current = null;
      }
      if (referenceLayerRef.current) {
        try {
          referenceLayerRef.current.remove();
        } catch (e) {
          // ignore
        }
        referenceLayerRef.current = null;
      }
      if (mapInstanceRef.current) {
        try {
          mapInstanceRef.current.remove();
        } catch (e) {
          console.warn('Map unmount cleanup:', e);
        }
        mapInstanceRef.current = null;
      }
      if (mapRef) {
        mapRef.current = null;
      }
      if (container && (container as any)._leaflet_id) {
        delete (container as any)._leaflet_id;
      }
    };
  }, []);

  // 2. Basemap switcher
  useEffect(() => {
    if (!mapInstanceRef.current || !tileLayerRef.current) return;
    const url = getBasemapUrl(basemap);
    tileLayerRef.current.setUrl(url);

    if (basemap === 'dark') {
      if (!referenceLayerRef.current) {
        referenceLayerRef.current = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
          { attribution: 'Tiles © Esri', maxZoom: 16 }
        ).addTo(mapInstanceRef.current);
      }
    } else {
      if (referenceLayerRef.current) {
        referenceLayerRef.current.remove();
        referenceLayerRef.current = null;
      }
    }
  }, [basemap]);

  // 3. Mutually exclusive active layer engine synchronization
  useEffect(() => {
    // 3.0 Real Satellite Imagery Layer (Esri World Imagery)
    if (activeLayer === 'satellite') {
      if (!satelliteTileLayerRef.current && mapInstanceRef.current) {
        satelliteTileLayerRef.current = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          { attribution: 'Satellite Imagery © Esri', maxZoom: 18 }
        ).addTo(mapInstanceRef.current);
      }
    } else {
      if (satelliteTileLayerRef.current) {
        satelliteTileLayerRef.current.remove();
        satelliteTileLayerRef.current = null;
      }
    }

    // 3.0b Real Doppler Weather Radar Layer (RainViewer)
    if (activeLayer === 'radar') {
      if (!radarTileLayerRef.current && mapInstanceRef.current) {
        fetch('https://api.rainviewer.com/public/weather-maps.json')
          .then((res) => res.json())
          .then((data) => {
            if (activeLayer === 'radar' && mapInstanceRef.current && data?.radar?.past?.length) {
              const latest = data.radar.past[data.radar.past.length - 1];
              const radarUrl = `${data.host}${latest.path}/256/{z}/{x}/{y}/2/1_1.png`;
              if (radarTileLayerRef.current) {
                radarTileLayerRef.current.remove();
              }
              radarTileLayerRef.current = L.tileLayer(radarUrl, {
                opacity: 0.85,
                maxZoom: 12,
                attribution: 'Radar © RainViewer',
              }).addTo(mapInstanceRef.current);
            }
          })
          .catch(() => {
            // Fallback handled by HeatmapCanvasLayer
          });
      }
    } else {
      if (radarTileLayerRef.current) {
        radarTileLayerRef.current.remove();
        radarTileLayerRef.current = null;
      }
    }

    // 3.1 Heatmap layer: renders only the selected layer (or clears if 'none', 'wind', or 'satellite')
    if (heatmapEngineRef.current) {
      heatmapEngineRef.current.setLayer(activeLayer);
      heatmapEngineRef.current.setShowPressureIsolines(showPressureIsolines);
    }

    // 3.2 Wind particle engine: ONLY runs when activeLayer === 'wind' AND showParticles
    if (particleEngineRef.current) {
      if (activeLayer === 'wind' && showParticles) {
        particleEngineRef.current.start();
      } else {
        particleEngineRef.current.stop();
        particleEngineRef.current.clear();
      }
    }

    // 3.3 Grid labels layer: renders contextual data for activeLayer, cleared otherwise
    if (labelsEngineRef.current) {
      labelsEngineRef.current.setMode(activeLayer);
    }
  }, [activeLayer, showParticles, showPressureIsolines]);

  // 4. Time offset changes
  useEffect(() => {
    if (particleEngineRef.current) {
      particleEngineRef.current.setTimeOffset(timeOffsetHours);
    }
    if (heatmapEngineRef.current) {
      heatmapEngineRef.current.setTimeOffset(timeOffsetHours);
    }
    if (labelsEngineRef.current) {
      labelsEngineRef.current.setTimeOffset(timeOffsetHours);
    }
  }, [timeOffsetHours]);

  // 5. Altitude changes
  useEffect(() => {
    if (particleEngineRef.current) {
      particleEngineRef.current.setAltitudeLevel(altitudeLevel);
    }
    if (heatmapEngineRef.current) {
      heatmapEngineRef.current.setAltitudeLevel(altitudeLevel);
    }
    if (labelsEngineRef.current) {
      labelsEngineRef.current.setAltitudeLevel(altitudeLevel);
    }
  }, [altitudeLevel]);

  // 6. Particle Density
  useEffect(() => {
    if (particleEngineRef.current) {
      particleEngineRef.current.setDensity(particleDensity);
    }
  }, [particleDensity]);

  // 7. Wind unit toggle
  useEffect(() => {
    if (labelsEngineRef.current) {
      labelsEngineRef.current.setWindUnit(windUnit);
    }
  }, [windUnit]);

  // 8. Temp unit toggle
  useEffect(() => {
    if (labelsEngineRef.current) {
      labelsEngineRef.current.setTempUnit(tempUnit);
    }
  }, [tempUnit]);

  // 9. Selected location updates picker
  useEffect(() => {
    if (selectedLocation) {
      const vector = computeWindVector(selectedLocation.lat, selectedLocation.lon, timeOffsetHours, altitudeLevel);
      const radLat = (selectedLocation.lat * Math.PI) / 180;
      const approxTemp = Math.round(30 * Math.cos(radLat * 1.1) + 2);

      setPickerData({
        lat: selectedLocation.lat,
        lon: selectedLocation.lon,
        speedKnots: vector.speedKnots,
        speedKmh: Math.round(vector.speed),
        dirDeg: vector.dirDeg,
        temp: approxTemp,
      });
    }
  }, [selectedLocation, timeOffsetHours, altitudeLevel]);

  // 10. Render ATHER Meteorological Point Picker
  useEffect(() => {
    if (!mapInstanceRef.current) return;

    if (!pickerData) {
      if (pickerMarkerRef.current) {
        mapInstanceRef.current.removeLayer(pickerMarkerRef.current);
        pickerMarkerRef.current = null;
      }
      return;
    }

    let displaySpeed = pickerData.speedKnots;
    let unitLabel = 'kt';
    if (windUnit === 'kmh') {
      displaySpeed = pickerData.speedKmh;
      unitLabel = 'km/h';
    } else if (windUnit === 'ms') {
      displaySpeed = Math.round(pickerData.speedKmh / 3.6);
      unitLabel = 'm/s';
    } else if (windUnit === 'mph') {
      displaySpeed = Math.round(pickerData.speedKmh * 0.621371);
      unitLabel = 'mph';
    }

    const displayTemp = tempUnit === 'c' 
      ? pickerData.temp 
      : Math.round((pickerData.temp * 9) / 5 + 32);

    const iconHtml = `
      <div class="relative transform -translate-x-1/2 -translate-y-1/2 group select-none pointer-events-auto">
        <div class="bg-[#1b2028]/95 border border-white/20 rounded-xl px-2.5 py-1.5 shadow-2xl flex items-center gap-2 text-white min-w-[130px] backdrop-blur-md">
          <div class="flex flex-col">
            <span class="text-[13px] font-black text-amber-400">${displayTemp}°${tempUnit.toUpperCase()}</span>
            <span class="text-[9px] text-slate-400 font-mono">${pickerData.lat.toFixed(1)}°, ${pickerData.lon.toFixed(1)}°</span>
          </div>
          <div class="w-[1px] h-6 bg-white/15"></div>
          <div class="flex items-center gap-1">
            <div class="text-[12px] font-bold text-sky-300" style="transform: rotate(${pickerData.dirDeg}deg); display: inline-block;">
              ↑
            </div>
            <div class="flex flex-col">
              <span class="text-[12px] font-bold text-sky-200">${displaySpeed} <span class="text-[9px] font-normal text-slate-400">${unitLabel}</span></span>
            </div>
          </div>
        </div>
        <div class="w-2.5 h-2.5 rounded-full bg-white border-2 border-sky-400 absolute top-0 left-0 -translate-x-1/2 -translate-y-1/2 shadow-lg"></div>
      </div>
    `;

    const customIcon = L.divIcon({
      html: iconHtml,
      className: 'ather-picker-icon',
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    });

    if (pickerMarkerRef.current) {
      pickerMarkerRef.current.setLatLng([pickerData.lat, pickerData.lon]);
      pickerMarkerRef.current.setIcon(customIcon);
    } else {
      pickerMarkerRef.current = L.marker([pickerData.lat, pickerData.lon], {
        icon: customIcon,
        zIndexOffset: 1000,
      }).addTo(mapInstanceRef.current);
    }
  }, [pickerData, windUnit, tempUnit]);

  // 11. Render Webcams Markers
  useEffect(() => {
    if (!webcamLayerGroupRef.current) return;
    webcamLayerGroupRef.current.clearLayers();

    if (!showWebcams) return;

    webcams.forEach((cam) => {
      const camIcon = L.divIcon({
        html: `
          <div id="webcam-pin-${cam.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform">
            <div class="w-7 h-7 rounded-full bg-sky-600/95 border-2 border-white text-white flex items-center justify-center shadow-xl backdrop-blur-sm">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
            </div>
            <div class="absolute -bottom-1 left-1/2 -translate-x-1/2 w-1.5 h-1.5 bg-white rounded-full"></div>
          </div>
        `,
        className: 'webcam-marker-icon',
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const marker = L.marker([cam.lat, cam.lon], { icon: camIcon });
      marker.on('click', () => {
        onSelectWebcam(cam);
      });
      webcamLayerGroupRef.current?.addLayer(marker);
    });
  }, [showWebcams, webcams, onSelectWebcam]);

  // 12. Index and Render Global NOAA ISD Weather Stations with Supercluster
  useEffect(() => {
    if (!globalStations || globalStations.length === 0) {
      superclusterRef.current = null;
      stationLayerGroupRef.current?.clearLayers();
      return;
    }

    const index = new Supercluster({
      radius: 75,
      maxZoom: 15,
    });

    // Filter by station type if selected
    const filteredStations = stationType
      ? globalStations.filter((s) => {
          if (stationType === 'airp') return Boolean(s.icao) || s.name.includes('AP') || s.name.includes('AIRPORT') || s.name.includes('INTL');
          if (stationType === 'wmo') return s.wban && s.wban !== '99999';
          return true;
        })
      : globalStations;

    const points = filteredStations.map((s) => ({
      type: 'Feature' as const,
      properties: {
        cluster: false,
        id: s.id,
        name: s.name,
        country: s.country,
        state: s.state,
        elev: s.elev,
        icao: s.icao,
        usaf: s.usaf,
        wban: s.wban,
      },
      geometry: {
        type: 'Point' as const,
        coordinates: [s.lon, s.lat] as [number, number],
      },
    }));

    index.load(points);
    superclusterRef.current = index;
    renderVisibleClusters();
  }, [globalStations, stationType]);

  const renderVisibleClusters = useCallback(() => {
    const startTime = performance.now();
    const map = mapInstanceRef.current;
    const index = superclusterRef.current;
    const layerGroup = stationLayerGroupRef.current;
    const canvasRenderer = canvasRendererRef.current;
    if (!map || !layerGroup) return;

    if (!showGlobalStations) {
      activeStationLayersRef.current.forEach((layer) => layerGroup.removeLayer(layer));
      activeStationLayersRef.current.clear();
      setPerfStats((prev) => ({ ...prev, visibleCount: 0, clustersCount: 0, individualCount: 0 }));
      return;
    }

    const bounds = map.getBounds();
    const rawZoom = map.getZoom();
    const zoom = Math.floor(rawZoom);

    let west = bounds.getWest();
    let east = bounds.getEast();
    let south = Math.max(-85, bounds.getSouth());
    let north = Math.min(85, bounds.getNorth());

    if (east - west >= 360) {
      west = -180;
      east = 180;
    } else {
      west = Math.max(-180, Math.min(180, west));
      east = Math.max(-180, Math.min(180, east));
    }

    const nextLayers = new Map<string, L.Layer>();
    let levelName = '';
    let clustersCount = 0;
    let individualCount = 0;

    // -------------------------------------------------------------
    // LEVEL 1: WORLD VIEW (Zoom < 4.0)
    // -------------------------------------------------------------
    if (rawZoom < 4.0) {
      levelName = 'Level 1: World Grid Aggregation';
      const gridCells = getGlobalGridCells();

      gridCells.forEach((cell) => {
        // Viewport bounding box check
        if (cell.lat < south || cell.lat > north) return;
        if (west <= east) {
          if (cell.lon < west || cell.lon > east) return;
        } else {
          if (cell.lon > east && cell.lon < west) return;
        }

        const key = `grid-${cell.cellId}`;
        clustersCount++;

        const existing = activeStationLayersRef.current.get(key);
        if (existing) {
          nextLayers.set(key, existing);
        } else {
          const countFormatted = cell.count >= 1000 ? `${(cell.count / 1000).toFixed(1)}k` : `${cell.count}`;
          let bubbleColor = 'bg-sky-950/90 border-sky-400/80 text-sky-200';
          if (cell.count >= 2000) {
            bubbleColor = 'bg-purple-950/90 border-purple-400 text-purple-100 font-bold';
          } else if (cell.count >= 500) {
            bubbleColor = 'bg-indigo-950/90 border-indigo-400 text-indigo-100 font-semibold';
          }

          const icon = L.divIcon({
            html: `
              <div class="transform -translate-x-1/2 -translate-y-1/2 cursor-pointer transition-transform hover:scale-110 select-none flex flex-col items-center">
                <div class="px-2 py-0.5 rounded-full ${bubbleColor} border shadow-lg backdrop-blur-sm text-[11px] font-mono flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                  <span>${countFormatted}</span>
                </div>
              </div>
            `,
            className: 'ather-grid-cell',
            iconSize: [0, 0],
            iconAnchor: [0, 0],
          });

          const marker = L.marker([cell.lat, cell.lon], { icon });
          marker.on('click', () => {
            map.flyTo([cell.lat, cell.lon], 5.5, { duration: 0.6 });
          });
          layerGroup.addLayer(marker);
          nextLayers.set(key, marker);
        }
      });
    }
    // -------------------------------------------------------------
    // LEVEL 2, 3, 4: REGIONAL, LOCAL & HIGH ZOOM (Using Supercluster)
    // -------------------------------------------------------------
    else if (index) {
      let queryZoom = Math.min(15, zoom);
      if (rawZoom < 7.0) {
        levelName = 'Level 2: Regional Clusters';
        queryZoom = Math.min(5, zoom);
      } else if (rawZoom < 10.0) {
        levelName = 'Level 3: Local Viewport Clusters';
        queryZoom = Math.min(8, zoom);
      } else {
        levelName = 'Level 4: High Zoom Station Dots';
      }

      let clusters = index.getClusters([west, south, east, north], queryZoom);

      // Check if individual stations would exceed 500; if so, step back zoom to keep clustering!
      let individualItems = clusters.filter((c) => !(c.properties as any).cluster);
      if (individualItems.length > 500 && queryZoom > 4) {
        queryZoom = Math.max(4, queryZoom - 2);
        clusters = index.getClusters([west, south, east, north], queryZoom);
        individualItems = clusters.filter((c) => !(c.properties as any).cluster);
        levelName += ' (Throttled)';
      }

      // HARD CAP: Max 500 individual stations rendered
      const allowedIndividuals = new Set(individualItems.slice(0, 500).map((c) => (c.properties as any).id));

      clusters.forEach((cluster) => {
        const [lon, lat] = cluster.geometry.coordinates;
        const isCluster = (cluster.properties as any).cluster;

        if (isCluster) {
          clustersCount++;
          const count = (cluster.properties as any).point_count;
          const key = `cluster-${cluster.id}-${count}`;

          const existing = activeStationLayersRef.current.get(key);
          if (existing) {
            nextLayers.set(key, existing);
          } else {
            const countFormatted = count >= 1000 ? `${(count / 1000).toFixed(1)}k` : `${count}`;
            let badgeColor = 'bg-sky-950/90 border-sky-400 text-sky-200';
            let size = 'w-7 h-7 text-[11px]';
            if (count >= 1000) {
              badgeColor = 'bg-purple-950/95 border-purple-400 text-purple-100 font-extrabold shadow-[0_0_15px_rgba(168,85,247,0.5)]';
              size = 'w-10 h-10 text-[12px]';
            } else if (count >= 100) {
              badgeColor = 'bg-indigo-950/90 border-indigo-400 text-indigo-100 font-bold shadow-[0_0_10px_rgba(129,140,248,0.4)]';
              size = 'w-8 h-8 text-[11.5px]';
            }

            const clusterIcon = L.divIcon({
              html: `
                <div class="transform -translate-x-1/2 -translate-y-1/2 cursor-pointer transition-transform hover:scale-110 select-none">
                  <div class="${size} ${badgeColor} rounded-full border flex items-center justify-center font-mono shadow-xl backdrop-blur-md">
                    ${countFormatted}
                  </div>
                </div>
              `,
              className: 'ather-cluster-marker',
              iconSize: [0, 0],
              iconAnchor: [0, 0],
            });

            const marker = L.marker([lat, lon], { icon: clusterIcon });
            marker.on('click', () => {
              const expansionZoom = Math.min(index.getClusterExpansionZoom(cluster.id as number), 16);
              map.flyTo([lat, lon], expansionZoom, { duration: 0.6 });
            });
            layerGroup.addLayer(marker);
            nextLayers.set(key, marker);
          }
        } else {
          // Individual Station Marker (Canvas-based)
          const st = cluster.properties as any;
          if (!allowedIndividuals.has(st.id)) return; // Strictly enforce max 500
          individualCount++;

          const isSelected = selectedGlobalStation?.id === st.id;
          const key = `station-${st.id}${isSelected ? '-sel' : ''}`;

          const existing = activeStationLayersRef.current.get(key);
          if (existing) {
            nextLayers.set(key, existing);
          } else {
            let marker: L.Layer;

            if (isSelected) {
              // Selected station dot with glowing halo
              const selectedHtml = `
                <div class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 select-none z-[950]">
                  <span class="absolute -inset-2 rounded-full bg-cyan-400/40 animate-ping"></span>
                  <div class="w-4 h-4 rounded-full bg-cyan-300 border-2 border-white shadow-[0_0_16px_rgba(6,182,212,1)] flex items-center justify-center">
                    <div class="w-1.5 h-1.5 rounded-full bg-[#12151b]"></div>
                  </div>
                </div>
              `;
              const icon = L.divIcon({
                html: selectedHtml,
                className: 'ather-selected-station-dot',
                iconSize: [0, 0],
                iconAnchor: [0, 0],
              });
              marker = L.marker([lat, lon], { icon, zIndexOffset: 1000 });
            } else {
              // Normal station rendered directly on HTML5 Canvas (zero DOM elements!)
              marker = L.circleMarker([lat, lon], {
                renderer: canvasRenderer || undefined,
                radius: 3.5,
                color: '#0ea5e9',
                fillColor: '#38bdf8',
                fillOpacity: 0.85,
                weight: 1.5,
              });
            }

            marker.bindTooltip(
              `<div class="p-1 font-mono text-[11px] leading-tight">
                <div class="font-bold text-sky-300">${st.name}</div>
                <div class="text-slate-300 text-[10px] mt-0.5">${st.id} • ${st.country || 'Global'} ${st.elev ? `• ${st.elev}m` : ''}</div>
              </div>`,
              { direction: 'top', offset: [0, -6], className: 'ather-tooltip' }
            );

            marker.on('click', (e) => {
              L.DomEvent.stopPropagation(e);
              if (onSelectGlobalStation) {
                onSelectGlobalStation({
                  id: st.id,
                  name: st.name,
                  lat,
                  lon,
                  country: st.country,
                  state: st.state,
                  elev: st.elev,
                  icao: st.icao,
                  usaf: st.usaf,
                  wban: st.wban,
                });
              }
            });

            layerGroup.addLayer(marker);
            nextLayers.set(key, marker);
          }
        }
      });
    }

    // Diff: Remove layers no longer visible
    activeStationLayersRef.current.forEach((layer, key) => {
      if (!nextLayers.has(key)) {
        layerGroup.removeLayer(layer);
      }
    });
    activeStationLayersRef.current = nextLayers;

    const elapsed = Math.round((performance.now() - startTime) * 10) / 10;

    // Update Dev Performance HUD
    setPerfStats({
      totalStations: globalStations.length,
      level: levelName,
      visibleCount: clustersCount + individualCount,
      clustersCount,
      individualCount,
      zoom: Math.round(rawZoom * 10) / 10,
      renderTimeMs: elapsed,
      openMeteoReqs: getOpenMeteoRequestCount(),
    });
  }, [showGlobalStations, selectedGlobalStation, onSelectGlobalStation, globalStations]);

  useEffect(() => {
    renderClustersRef.current = renderVisibleClusters;
    renderVisibleClusters();
  }, [renderVisibleClusters]);

  // 13. Render AWS (Automatic Weather Stations) Markers with ATHER Modes
  useEffect(() => {
    if (!awsLayerGroupRef.current) return;
    awsLayerGroupRef.current.clearLayers();

    if (!showAwsStations) return;

    const list = awsStations && awsStations.length > 0 ? awsStations : DEFAULT_AWS_STATIONS;

    list.forEach((st) => {
      const displayTemp = tempUnit === 'c' ? Math.round(st.temp * 10) / 10 : Math.round((st.temp * 9) / 5 + 32);
      const isSelected = selectedStation?.id === st.id;
      const analysis = st.latestAnalysis;
      const isCritical = analysis?.severity === 'Critical' || st.healthStatus === 'critical';
      const isWarning = analysis?.severity === 'Warning' || st.healthStatus === 'warning';

      let markerHtml = '';

      if (mapMode === 'anomalies') {
        // AI Anomalies Mode: Emphasize anomalous and warning stations with root cause!
        if (isCritical) {
          markerHtml = `
            <div id="aws-pin-${st.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none z-[800]">
              <span class="absolute -inset-2 rounded-full bg-rose-500/50 animate-ping"></span>
              <div class="relative px-2.5 py-1 rounded-full bg-rose-950/95 border-2 ${isSelected ? 'border-white ring-2 ring-rose-400' : 'border-rose-500'} text-white font-mono text-[10px] flex items-center gap-1.5 shadow-2xl backdrop-blur-md">
                <span class="w-2 h-2 rounded-full bg-rose-400 animate-pulse"></span>
                <span class="font-extrabold text-white">${st.id}</span>
                <span class="text-amber-300 font-bold">${displayTemp}°</span>
                <span class="px-1 py-0.2 rounded bg-rose-600 text-[9px] font-black uppercase text-white tracking-wide">
                  ⚠️ ${analysis?.anomalyScore || 94}% CRITICAL
                </span>
              </div>
            </div>
          `;
        } else if (isWarning) {
          markerHtml = `
            <div id="aws-pin-${st.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none z-[600]">
              <span class="absolute -inset-1 rounded-full bg-amber-500/30 animate-pulse"></span>
              <div class="relative px-2 py-0.5 rounded-full bg-[#201a14]/95 border ${isSelected ? 'border-white ring-2 ring-amber-400' : 'border-amber-400/90'} text-white font-mono text-[10px] flex items-center gap-1.5 shadow-xl backdrop-blur-md">
                <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                <span class="font-bold text-slate-100">${st.id}</span>
                <span class="text-amber-300">${displayTemp}°</span>
                <span class="text-amber-300 text-[9px] font-bold">⚠️ ${analysis?.anomalyScore || 62}%</span>
              </div>
            </div>
          `;
        } else {
          // Normal stations are dimmed in anomaly mode so anomalous stations pop
          markerHtml = `
            <div id="aws-pin-${st.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none opacity-60 hover:opacity-100">
              <div class="px-2 py-0.5 rounded-full bg-[#161c26]/85 border border-slate-600/60 text-slate-300 font-mono text-[9.5px] flex items-center gap-1.5 shadow backdrop-blur-sm">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                <span class="text-slate-300">${st.id.replace('AWS-', '')}</span>
                <span class="text-slate-200">${displayTemp}°</span>
              </div>
            </div>
          `;
        }
      } else if (mapMode === 'health') {
        // Sensor Health Mode: Visually communicates sensor health & degradation drift
        const healthPercent = Math.round(st.healthPercent);
        const healthBg =
          healthPercent >= 80
            ? 'border-emerald-400/80 bg-[#12231c]/90 text-emerald-200'
            : healthPercent >= 50
            ? 'border-amber-400/80 bg-[#251f15]/90 text-amber-200'
            : 'border-rose-400/90 bg-[#2b1419]/95 text-rose-200';

        const dotColor =
          healthPercent >= 80 ? 'bg-emerald-400' : healthPercent >= 50 ? 'bg-amber-400' : 'bg-rose-400';

        markerHtml = `
          <div id="aws-pin-${st.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none">
            <div class="px-2 py-0.5 rounded-full ${healthBg} border ${isSelected ? 'ring-2 ring-white scale-105' : ''} font-mono text-[10px] flex items-center gap-1.5 shadow-xl backdrop-blur-md">
              <span class="w-1.5 h-1.5 rounded-full ${dotColor} ${healthPercent < 80 ? 'animate-pulse' : ''}"></span>
              <span class="font-bold">${st.id}</span>
              <span class="font-black px-1 rounded bg-black/40 text-[9.5px]">${healthPercent}% Health</span>
              ${st.healthTrend === 'degrading' ? '<span class="text-rose-400 text-[9px]">▼</span>' : ''}
            </div>
          </div>
        `;
      } else {
        // Standard AWS Network Monitoring Mode
        const dotColor =
          isCritical ? 'bg-rose-400 animate-ping' : isWarning ? 'bg-amber-400' : 'bg-emerald-400 animate-pulse';
        const borderColor =
          isSelected
            ? 'border-white ring-2 ring-sky-400'
            : isCritical
            ? 'border-rose-400/90'
            : isWarning
            ? 'border-amber-400/80'
            : 'border-emerald-400/80';

        markerHtml = `
          <div id="aws-pin-${st.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none">
            <div class="px-2 py-0.5 rounded-full bg-[#161c26]/90 border ${borderColor} text-white font-mono text-[10px] flex items-center gap-1.5 shadow-xl backdrop-blur-md">
              <span class="w-1.5 h-1.5 rounded-full ${dotColor}"></span>
              <span class="font-bold text-slate-100">${st.id}</span>
              <span class="text-amber-300 font-semibold">${displayTemp}°</span>
              <span class="text-[9px] ${st.healthPercent >= 80 ? 'text-emerald-300' : 'text-amber-300'} font-bold">${Math.round(st.healthPercent)}%</span>
            </div>
          </div>
        `;
      }

      const awsIcon = L.divIcon({
        html: markerHtml,
        className: 'aws-station-marker-icon',
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const marker = L.marker([st.lat, st.lon], { 
        icon: awsIcon,
        zIndexOffset: isCritical ? 900 : isWarning ? 500 : 100 
      });

      // Click opens the ATHER Station Drawer
      marker.on('click', () => {
        onSelectStation?.(st);
      });

      awsLayerGroupRef.current?.addLayer(marker);
    });
  }, [showAwsStations, tempUnit, awsStations, selectedStation, onSelectStation, mapMode]);

  // 13b. Spatial Intelligence Context Layer: Render dashed radius and nearest-neighbor consensus lines
  useEffect(() => {
    if (!spatialLayerGroupRef.current) return;
    spatialLayerGroupRef.current.clearLayers();

    if (!showAwsStations || !selectedStation) return;

    const list = awsStations && awsStations.length > 0 ? awsStations : DEFAULT_AWS_STATIONS;

    // 1. Subtle spatial neighborhood comparison radius (~170 km)
    const circle = L.circle([selectedStation.lat, selectedStation.lon], {
      radius: 170000,
      color: '#38bdf8',
      weight: 1.2,
      dashArray: '5, 8',
      fillColor: '#0284c7',
      fillOpacity: 0.03,
      interactive: false,
    });
    spatialLayerGroupRef.current.addLayer(circle);

    // 2. Compute 4 nearest neighbor AWS stations
    const neighbors = list
      .filter((s) => s.id !== selectedStation.id)
      .map((s) => ({
        station: s,
        distanceKm: Math.round(calculateHaversineDistance(selectedStation.lat, selectedStation.lon, s.lat, s.lon)),
      }))
      .sort((a, b) => a.distanceKm - b.distanceKm)
      .slice(0, 4);

    // 3. Draw dashed spatial comparison lines and delta badges
    neighbors.forEach(({ station: n, distanceKm }) => {
      const deltaT = Math.round((selectedStation.currentObs.temperature - n.currentObs.temperature) * 10) / 10;
      const isSevereDiscrepancy = Math.abs(deltaT) > 10;
      const lineColor = isSevereDiscrepancy ? '#f43f5e' : '#38bdf8';

      const line = L.polyline(
        [
          [selectedStation.lat, selectedStation.lon],
          [n.lat, n.lon],
        ],
        {
          color: lineColor,
          weight: isSevereDiscrepancy ? 2 : 1.5,
          opacity: isSevereDiscrepancy ? 0.8 : 0.45,
          dashArray: '5, 7',
          interactive: false,
        }
      );
      spatialLayerGroupRef.current?.addLayer(line);

      // Midpoint delta badge
      const midLat = (selectedStation.lat + n.lat) / 2;
      const midLon = (selectedStation.lon + n.lon) / 2;
      const deltaSign = deltaT > 0 ? `+${deltaT}` : `${deltaT}`;
      const badgeClass = isSevereDiscrepancy
        ? 'bg-rose-950/95 text-rose-200 border-rose-500/70'
        : 'bg-[#121622]/90 text-sky-200 border-sky-400/40';

      const badgeHtml = `
        <div class="transform -translate-x-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded-full ${badgeClass} border text-[9px] font-mono font-bold shadow-lg whitespace-nowrap pointer-events-none select-none backdrop-blur-sm">
          Δ ${deltaSign}° (${distanceKm}km)
        </div>
      `;

      const badgeIcon = L.divIcon({
        html: badgeHtml,
        className: 'spatial-delta-badge',
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const badgeMarker = L.marker([midLat, midLon], { icon: badgeIcon, interactive: false });
      spatialLayerGroupRef.current?.addLayer(badgeMarker);
    });
  }, [selectedStation, awsStations, tempUnit, showAwsStations]);

  // 14. Render ATHER Anomaly Markers (Decoupled from weather layers)
  useEffect(() => {
    if (!anomalyLayerGroupRef.current) return;
    anomalyLayerGroupRef.current.clearLayers();

    if (!showAnomalyMarkers) return;

    AI_ANOMALIES.forEach((anom) => {
      const isCritical = anom.level === 'D5';
      const badgeBg = isCritical ? 'bg-rose-600 border-rose-400' : 'bg-amber-600 border-amber-400';
      const pulseBg = isCritical ? 'bg-rose-500/40' : 'bg-amber-500/40';

      const anomIcon = L.divIcon({
        html: `
          <div id="anom-pin-${anom.id}" class="relative cursor-pointer group transform -translate-x-1/2 -translate-y-1/2 hover:scale-110 transition-transform select-none">
            <span class="absolute -inset-1 rounded-full ${pulseBg} animate-ping"></span>
            <div class="relative px-2 py-0.5 rounded-full ${badgeBg} border text-white font-bold text-[10px] flex items-center gap-1 shadow-2xl backdrop-blur-sm">
              <span>⚠️</span>
              <span>${anom.level}</span>
              <span class="font-mono text-[9px] bg-black/30 px-1 rounded">${anom.riskScore}%</span>
            </div>
          </div>
        `,
        className: 'ai-anomaly-marker-icon',
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const marker = L.marker([anom.lat, anom.lon], { icon: anomIcon });
      marker.bindPopup(`
        <div class="p-1 text-slate-900 min-w-[210px]">
          <div class="font-bold text-xs flex items-center justify-between border-b pb-1 mb-1">
            <span class="text-rose-700">ATHER Anomaly Alert</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded ${isCritical ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'} font-bold">${anom.level} (${anom.riskScore}%)</span>
          </div>
          <div class="font-semibold text-[11px] text-slate-800 mb-1">${anom.title}</div>
          <div class="text-[10px] text-slate-600 leading-relaxed mb-1.5">${anom.desc}</div>
          <div class="text-[9px] text-slate-400 font-mono">Location: ${anom.lat.toFixed(1)}°N, ${anom.lon.toFixed(1)}°E</div>
        </div>
      `, {
        className: 'ather-popup',
      });
      anomalyLayerGroupRef.current?.addLayer(marker);
    });
  }, [showAnomalyMarkers]);

  return (
    <div 
      id="ather-map-wrapper"
      className="relative w-full h-screen overflow-hidden bg-[#12151b]"
      style={{
        width: '100vw',
        height: '100vh',
        perspective: is3D ? '1100px' : 'none',
      }}
    >
      {/* 3D Tilted Map Stage */}
      <div 
        id="ather-map-stage"
        className="w-full h-full relative transition-transform duration-700 ease-out"
        style={{
          width: '100%',
          height: '100%',
          transform: is3D ? 'rotateX(26deg) scale(1.05)' : 'none',
          transformOrigin: 'center 85%',
        }}
      >
        {/* Leaflet Base Map */}
        <div 
          ref={mapContainerRef} 
          id="map-container"
          className="absolute inset-0 z-0" 
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
        />

        {/* Heatmap Color Canvas (temp, rain, wind velocity field, pressure) */}
        <canvas
          ref={heatmapCanvasRef}
          id="heatmap-canvas"
          className="absolute inset-0 z-10 pointer-events-none"
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
        />

        {/* Wind Streamline Particles Canvas (strictly hidden when activeLayer !== 'wind') */}
        <canvas
          ref={particleCanvasRef}
          id="particles-canvas"
          className={`absolute inset-0 z-20 pointer-events-none transition-opacity duration-300 ${activeLayer === 'wind' && showParticles ? 'opacity-100' : 'opacity-0'}`}
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
        />

        {/* Wind Speed Labels with directional arrows Canvas */}
        <canvas
          ref={labelsCanvasRef}
          id="labels-canvas"
          className="absolute inset-0 z-30 pointer-events-none"
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
        />
      </div>

      {/* Developer Performance HUD (Real-time monitoring of object counts and render latency) */}
      <div
        id="ather-perf-hud"
        className="fixed bottom-2 left-2 z-[900] bg-[#10141d]/90 backdrop-blur-md border border-white/10 rounded-xl px-2.5 py-1.5 text-[10px] font-mono text-slate-300 shadow-xl pointer-events-auto select-none space-y-0.5"
      >
        <div className="flex items-center justify-between gap-3 text-sky-400 font-bold border-b border-white/10 pb-0.5 mb-1">
          <span className="flex items-center gap-1">⚡ ATHER PERF HUD</span>
          <span className="text-[9px] px-1 py-0.2 rounded bg-sky-950 border border-sky-400/30 text-sky-300">
            {perfStats.level}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-slate-400">
          <span>Dataset: <strong className="text-white">{perfStats.totalStations.toLocaleString()}</strong></span>
          <span>Visible: <strong className="text-amber-300">{perfStats.visibleCount}</strong></span>
          <span>Clusters: <strong className="text-cyan-300">{perfStats.clustersCount}</strong></span>
          <span>Canvas Dots: <strong className="text-emerald-300">{perfStats.individualCount}</strong> (max 500)</span>
          <span>Map Zoom: <strong className="text-white">{perfStats.zoom}</strong></span>
          <span>Render Time: <strong className="text-emerald-400">{perfStats.renderTimeMs}ms</strong></span>
          <span>Open-Meteo Req: <strong className="text-white">{perfStats.openMeteoReqs}</strong></span>
        </div>
      </div>
    </div>
  );
};

function getBasemapUrl(basemap: MapBasemap): string {
  switch (basemap) {
    case 'satellite':
      return 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
    case 'voyager':
      return 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    case 'osm':
      return 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    case 'dark':
    default:
      return 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
  }
}
