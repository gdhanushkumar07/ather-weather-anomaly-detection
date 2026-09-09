import { useState, useCallback } from 'react';
import { WeatherMap } from './components/Map/WeatherMap';
import { TopBar } from './components/UI/TopBar';
import { LayerSwitcher } from './components/UI/LayerSwitcher';
import { TimelineSlider } from './components/UI/TimelineSlider';
import { AltitudeSlider } from './components/UI/AltitudeSlider';
import { ColorScaleLegend } from './components/UI/ColorScaleLegend';
import { CompactWeatherOverlay } from './components/UI/CompactWeatherOverlay';
import { WebcamModal } from './components/UI/WebcamModal';
import type {
  WeatherLayerType,
  AltitudeLevel,
  ForecastModel,
  LocationCoords,
  PointForecastData,
  AIAnomalyItem,
  WebcamItem,
} from './types/weather';
import { fetchPointForecast } from './utils/api';

export function App() {
  // 1. Initial layer is 'none' - pure clean base map, NO wind or overlays on initial load
  const [activeLayer, setActiveLayer] = useState<WeatherLayerType>('none');
  const [altitude, setAltitude] = useState<AltitudeLevel>('surface');
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [timeOffsetHours, setTimeOffsetHours] = useState<number>(0);
  const [selectedModel, setSelectedModel] = useState<ForecastModel>('ECMWF');
  const [unitSystem, setUnitSystem] = useState<'metric' | 'imperial'>('metric');

  // 2. Initial state: NO weather card shown until user clicks a location
  const [selectedLocation, setSelectedLocation] = useState<LocationCoords | null>(null);
  const [forecastData, setForecastData] = useState<PointForecastData | null>(null);
  const [forecastLoading, setForecastLoading] = useState<boolean>(false);
  const [overlayOpen, setOverlayOpen] = useState<boolean>(false);

  // 3. Optional modes (SkyGuard AI Anomalies and Webcams)
  const [selectedStation, setSelectedStation] = useState<AIAnomalyItem | null>(null);
  const [showWebcams, setShowWebcams] = useState<boolean>(false);
  const [selectedWebcam, setSelectedWebcam] = useState<WebcamItem | null>(null);

  // 4. Simulation parameters (Menu dropdown)
  const [particleDensity, setParticleDensity] = useState<number>(1.0);
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(1.0);

  // Fetch forecast data on user interaction (Click on map / Search / City pill)
  const loadForecast = useCallback(
    async (loc: LocationCoords) => {
      setForecastLoading(true);
      setOverlayOpen(true);
      try {
        const data = await fetchPointForecast(loc.lat, loc.lon, loc.name, selectedModel);
        setForecastData(data);
      } catch (err) {
        console.error('Forecast load error:', err);
      } finally {
        setForecastLoading(false);
      }
    },
    [selectedModel]
  );

  // Stable handlers wrapped in useCallback to guarantee map never re-initializes
  const handleMapClick = useCallback((lat: number, lon: number) => {
    const newLoc = { lat, lon };
    setSelectedLocation(newLoc);
    setSelectedStation(null);
    loadForecast(newLoc);
  }, [loadForecast]);

  const handleSelectLocation = useCallback((loc: LocationCoords) => {
    setSelectedLocation(loc);
    setSelectedStation(null);
    loadForecast(loc);
  }, [loadForecast]);

  const handleSelectStation = useCallback((station: AIAnomalyItem | null) => {
    setSelectedStation(station);
    if (station) {
      const loc = {
        lat: station.lat,
        lon: station.lon,
        name: station.stationName,
        country: 'India',
      };
      setSelectedLocation(loc);
      loadForecast(loc);
    }
  }, [loadForecast]);

  const handleTimeChange = useCallback((newHour: number) => {
    setTimeOffsetHours(newHour);
  }, []);

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#14181d] select-none">
      {/* 1. Full-Screen Interactive Weather Map (The Map is the Application) */}
      <WeatherMap
        activeLayer={activeLayer}
        altitude={altitude}
        isPlaying={isPlaying}
        timeOffsetHours={timeOffsetHours}
        selectedLocation={selectedLocation}
        onMapClick={handleMapClick}
        onSelectStation={handleSelectStation}
        onSelectWebcam={setSelectedWebcam}
        showWebcams={showWebcams}
        particleDensity={particleDensity}
        speedMultiplier={speedMultiplier}
      />

      {/* 2. Floating Top Navigation (SkyGuard AI, Search, Quick Pills, Badges) */}
      <TopBar
        onSelectLocation={handleSelectLocation}
        showWebcams={showWebcams}
        onToggleWebcams={() => setShowWebcams(!showWebcams)}
        onSelectAnomalies={() => {
          setActiveLayer(activeLayer === 'anomalies' ? 'none' : 'anomalies');
        }}
        isAnomalyActive={activeLayer === 'anomalies'}
        unitSystem={unitSystem}
        onToggleUnitSystem={() =>
          setUnitSystem(unitSystem === 'metric' ? 'imperial' : 'metric')
        }
        particleDensity={particleDensity}
        onDensityChange={setParticleDensity}
        speedMultiplier={speedMultiplier}
        onSpeedChange={setSpeedMultiplier}
      />

      {/* 3. Floating Right-Side Vertical Weather Layer Selector (Narrow Stack) */}
      <LayerSwitcher
        activeLayer={activeLayer}
        onSelectLayer={(layer) => {
          setActiveLayer(layer);
          if (layer === 'anomalies') setSelectedStation(null);
        }}
      />

      {/* 4. Dismissible Compact Weather Info Panel (Only appears when location is clicked) */}
      {overlayOpen && (
        <CompactWeatherOverlay
          data={forecastData}
          loading={forecastLoading}
          timeOffsetHours={timeOffsetHours}
          onClose={() => {
            setOverlayOpen(false);
            setSelectedLocation(null);
            setSelectedStation(null);
          }}
          selectedStation={selectedStation}
          unitSystem={unitSystem}
        />
      )}

      {/* 5. Altitude Selector (Only rendered when Wind layer is active) */}
      {activeLayer === 'wind' && (
        <AltitudeSlider
          altitude={altitude}
          onSelectAltitude={setAltitude}
        />
      )}

      {/* 6. Dynamic Color Scale Legend (Only shown when active overlay layer is selected) */}
      {activeLayer !== 'none' && activeLayer !== 'anomalies' && (
        <ColorScaleLegend
          layer={activeLayer}
          unitSystem={unitSystem}
        />
      )}

      {/* 7. Windy-Style Floating Forecast Timeline (Bottom Center) */}
      <TimelineSlider
        isPlaying={isPlaying}
        onTogglePlay={() => setIsPlaying(!isPlaying)}
        timeOffsetHours={timeOffsetHours}
        onTimeChange={handleTimeChange}
        selectedModel={selectedModel}
        onSelectModel={(m) => {
          setSelectedModel(m);
          if (selectedLocation) loadForecast(selectedLocation);
        }}
      />

      {/* 8. Live Webcam Stream Modal */}
      <WebcamModal
        webcam={selectedWebcam}
        onClose={() => setSelectedWebcam(null)}
      />
    </div>
  );
}

export default App;
