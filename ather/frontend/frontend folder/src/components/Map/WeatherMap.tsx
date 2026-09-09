import React, { useEffect, useRef, useState } from 'react';
import L, { type Map as LeafletMap } from 'leaflet';
import { WindParticleCanvas } from './WindParticleCanvas';
import { HeatmapOverlay } from './HeatmapOverlay';
import { AIAnomalyLayer } from './AIAnomalyLayer';
import { WebcamMarkers } from './WebcamMarkers';

import type {
  WeatherLayerType,
  AltitudeLevel,
  BaseMapStyle,
  LocationCoords,
  AIAnomalyItem,
  WebcamItem,
} from '../../types/weather';
import { Locate, Layers, Plus, Minus, Maximize } from 'lucide-react';

interface WeatherMapProps {
  activeLayer: WeatherLayerType;
  altitude: AltitudeLevel;
  isPlaying: boolean;
  timeOffsetHours: number;
  selectedLocation: LocationCoords | null;
  onMapClick: (lat: number, lon: number) => void;
  onSelectStation: (station: AIAnomalyItem) => void;
  onSelectWebcam: (webcam: WebcamItem) => void;
  showWebcams: boolean;
  particleDensity: number;
  speedMultiplier: number;
  // Command Center integration props (optional for backward compatibility)
  activeView?: string;
  showAnomalies?: boolean;
  selectedStation?: AIAnomalyItem | null;
}

export const WeatherMap: React.FC<WeatherMapProps> = ({
  activeLayer,
  altitude,
  isPlaying,
  timeOffsetHours,
  selectedLocation,
  onMapClick,
  onSelectStation,
  onSelectWebcam,
  showWebcams,
  particleDensity,
  speedMultiplier,
  activeView,
  showAnomalies,
  selectedStation,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [baseMapStyle, setBaseMapStyle] = useState<BaseMapStyle>('dark');
  const [showStyleMenu, setShowStyleMenu] = useState(false);
  const clickMarkerRef = useRef<L.Marker | null>(null);
  const baseTileLayerRef = useRef<L.TileLayer | null>(null);

  const onMapClickRef = useRef(onMapClick);
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  // Initialize Leaflet Map - runs ONCE and never destroys on time/prop updates
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    // Centered over India by default (matching SIH AWS deployment area)
    const map = L.map(mapContainerRef.current, {
      center: [20.5937, 78.9629],
      zoom: 5,
      minZoom: 2,
      maxZoom: 18,
      zoomControl: false,
      attributionControl: false,
    });

    // Esri World Dark Gray Base tile layer (clean mission-control backdrop)
    const darkTiles = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      {
        attribution: 'Tiles © Esri — Esri, DeLorme, NAVTEQ',
        maxZoom: 16,
      }
    ).addTo(map);

    baseTileLayerRef.current = darkTiles;
    mapInstanceRef.current = map;
    setMapReady(true);

    // Map Click Handler for Point Forecast Picker
    map.on('click', (e: L.LeafletMouseEvent) => {
      const { lat, lng } = e.latlng;
      onMapClickRef.current(lat, lng);
    });

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Handle Base Map Tile Switching
  useEffect(() => {
    if (!mapInstanceRef.current || !baseTileLayerRef.current) return;

    const map = mapInstanceRef.current;
    baseTileLayerRef.current.remove();

    let newUrl = '';
    let attribution = '';

    if (baseMapStyle === 'satellite') {
      newUrl = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
      attribution = 'Esri, Maxar, Earthstar';
    } else if (baseMapStyle === 'street') {
      newUrl = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
      attribution = 'OpenStreetMap';
    } else if (baseMapStyle === 'terrain') {
      newUrl = 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png';
      attribution = 'OpenTopoMap';
    } else {
      newUrl = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
      attribution = 'Tiles © Esri — Esri, DeLorme, NAVTEQ';
    }

    const newLayer = L.tileLayer(newUrl, { maxZoom: 16, attribution }).addTo(map);
    baseTileLayerRef.current = newLayer;
  }, [baseMapStyle]);

  // Sync Selected Location Pin
  useEffect(() => {
    if (!mapInstanceRef.current) return;
    const map = mapInstanceRef.current;

    if (clickMarkerRef.current) {
      clickMarkerRef.current.remove();
      clickMarkerRef.current = null;
    }

    if (selectedLocation) {
      const pickerIcon = L.divIcon({
        html: `
          <div class="relative flex items-center justify-center">
            <div class="absolute w-7 h-7 rounded-full bg-cyan-400/30 animate-ping"></div>
            <div class="w-5 h-5 rounded-full bg-cyan-400 border-2 border-white shadow-xl flex items-center justify-center text-[10px] font-black text-slate-900">
              ●
            </div>
          </div>
        `,
        className: 'picker-marker-icon',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      });

      const marker = L.marker([selectedLocation.lat, selectedLocation.lon], { icon: pickerIcon }).addTo(map);
      clickMarkerRef.current = marker;
    }
  }, [selectedLocation]);

  // Fly to location helper for selected coordinates
  useEffect(() => {
    if (!mapInstanceRef.current || !selectedLocation) return;
    const map = mapInstanceRef.current;
    const curCenter = map.getCenter();
    const dist = Math.hypot(curCenter.lat - selectedLocation.lat, curCenter.lng - selectedLocation.lon);
    if (dist > 3) {
      map.flyTo([selectedLocation.lat, selectedLocation.lon], Math.max(map.getZoom(), 8), {
        duration: 1.2,
      });
    }
  }, [selectedLocation]);

  // Fly to selected station if clicked from sidebar or panels
  useEffect(() => {
    if (!mapInstanceRef.current || !selectedStation) return;
    const map = mapInstanceRef.current;
    map.flyTo([selectedStation.lat, selectedStation.lon], Math.max(map.getZoom(), 8), {
      duration: 1.2,
    });
  }, [selectedStation]);

  const handleLocateMe = () => {
    if (!navigator.geolocation || !mapInstanceRef.current) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        mapInstanceRef.current?.flyTo([latitude, longitude], 10, { duration: 1.2 });
        onMapClick(latitude, longitude);
      },
      (err) => {
        console.warn('Geolocation failed:', err.message);
      }
    );
  };

  const handleZoomIn = () => mapInstanceRef.current?.zoomIn();
  const handleZoomOut = () => mapInstanceRef.current?.zoomOut();

  // AWS Stations remain visible during overview, anomalies, stations, or when anomalies layer is active
  const isAnomalyLayerVisible =
    showAnomalies ??
    (activeLayer === 'anomalies' ||
      activeView === 'anomalies' ||
      activeView === 'stations' ||
      activeView === 'overview' ||
      !activeView);

  return (
    <div className="relative w-full h-full overflow-hidden">
      {/* Map Container */}
      <div ref={mapContainerRef} className="absolute inset-0 z-0 bg-[#14181d]" />

      {/* Heatmap Layer Overlay (Rain, Temp, Clouds, Pressure, etc.) */}
      {mapReady && (
        <HeatmapOverlay
          map={mapInstanceRef.current}
          layer={activeLayer}
          timeOffsetHours={timeOffsetHours}
        />
      )}

      {/* Wind Particles Overlay */}
      {mapReady && (
        <WindParticleCanvas
          map={mapInstanceRef.current}
          isPlaying={isPlaying}
          timeOffsetHours={timeOffsetHours}
          altitude={altitude}
          particleDensity={particleDensity}
          speedMultiplier={speedMultiplier}
          visible={activeLayer === 'wind'}
        />
      )}

      {/* SIH Hackathon AI Anomaly Layer */}
      {mapReady && (
        <AIAnomalyLayer
          map={mapInstanceRef.current}
          visible={isAnomalyLayerVisible}
          onSelectStation={onSelectStation}
        />
      )}

      {/* Live Webcams Layer */}
      {mapReady && (
        <WebcamMarkers
          map={mapInstanceRef.current}
          visible={showWebcams}
          onSelectWebcam={onSelectWebcam}
        />
      )}

      {/* Map Navigation Controls positioned clearly to the right of CommandSidebar */}
      <div className="absolute bottom-6 left-[280px] z-20 flex flex-col gap-1.5">
        <div className="windy-glass rounded-lg overflow-hidden flex flex-col divide-y divide-white/10 shadow-xl">
          <button
            onClick={handleZoomIn}
            title="Zoom In"
            className="w-9 h-9 flex items-center justify-center text-slate-300 hover:text-cyan-400 hover:bg-white/10 transition-colors"
          >
            <Plus className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomOut}
            title="Zoom Out"
            className="w-9 h-9 flex items-center justify-center text-slate-300 hover:text-cyan-400 hover:bg-white/10 transition-colors"
          >
            <Minus className="w-4 h-4" />
          </button>
        </div>

        <button
          onClick={handleLocateMe}
          title="Locate my position"
          className="w-9 h-9 windy-glass rounded-lg flex items-center justify-center text-slate-300 hover:text-cyan-400 hover:bg-white/10 transition-colors shadow-xl"
        >
          <Locate className="w-4 h-4" />
        </button>

        {/* Base Map Switcher */}
        <div className="relative">
          <button
            onClick={() => setShowStyleMenu(!showStyleMenu)}
            title="Switch Map Tiles"
            className="w-9 h-9 windy-glass rounded-lg flex items-center justify-center text-slate-300 hover:text-cyan-400 hover:bg-white/10 transition-colors shadow-xl"
          >
            <Layers className="w-4 h-4" />
          </button>

          {showStyleMenu && (
            <div className="absolute top-0 left-11 windy-glass rounded-xl p-2 w-36 flex flex-col gap-1 shadow-2xl z-30 animate-in fade-in slide-in-from-left-2">
              <div className="text-[10px] uppercase font-bold text-slate-400 px-2 py-1 tracking-wider">
                Base Layer
              </div>
              {(['dark', 'satellite', 'terrain', 'street'] as BaseMapStyle[]).map((style) => (
                <button
                  key={style}
                  onClick={() => {
                    setBaseMapStyle(style);
                    setShowStyleMenu(false);
                  }}
                  className={`text-xs px-2.5 py-1.5 rounded-lg text-left capitalize transition-colors ${
                    baseMapStyle === style
                      ? 'bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/30'
                      : 'text-slate-300 hover:bg-white/10'
                  }`}
                >
                  {style}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Fullscreen Button */}
        <button
          onClick={() => {
            if (!document.fullscreenElement) {
              document.documentElement.requestFullscreen().catch(() => {});
            } else {
              document.exitFullscreen().catch(() => {});
            }
          }}
          title="Toggle Fullscreen"
          className="w-9 h-9 windy-glass rounded-lg flex items-center justify-center text-slate-300 hover:text-cyan-400 hover:bg-white/10 transition-colors shadow-xl"
        >
          <Maximize className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};