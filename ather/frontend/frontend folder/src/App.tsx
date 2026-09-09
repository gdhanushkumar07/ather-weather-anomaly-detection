import { useState, useCallback } from 'react';
import { StationsPanel } from './components/StationsPanel';
import { WeatherMap } from './components/Map/WeatherMap';
import { TopBar } from './components/UI/TopBar';
import { TimelineSlider } from './components/UI/TimelineSlider';
import { AltitudeSlider } from './components/UI/AltitudeSlider';
import { ColorScaleLegend } from './components/UI/ColorScaleLegend';
import { CompactWeatherOverlay } from './components/UI/CompactWeatherOverlay';
import { WebcamModal } from './components/UI/WebcamModal';
import { CommandSidebar } from './components/CommandSidebar'; 
import { LiveAlertPanel } from './components/LiveAlterPanel'; // Keeping your exact import path
import { BrainCircuit, Wrench, BarChart3, RadioTower } from 'lucide-react'; // Added for placeholder panels
import { AiInsights } from './components/AiInsights';
import { SelfHealingPanel } from './components/SelfHealingPanel';
import { AnalyticsPanel } from './components/AnalyticsPanel';
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
  // 1. Initial layer is 'none' - pure clean base map
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

  // 3. Optional modes
  const [selectedStation, setSelectedStation] = useState<AIAnomalyItem | null>(null);
  const [showWebcams, setShowWebcams] = useState<boolean>(false);
  const [selectedWebcam, setSelectedWebcam] = useState<WebcamItem | null>(null);

  // 4. Simulation parameters
  const [particleDensity, setParticleDensity] = useState<number>(1.0);
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(1.0);

  // 5. NEW: SIH Command Center Navigation State
  const [activeView, setActiveView] = useState<string>('overview');

  // Fetch forecast data on user interaction
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

  // Stable handlers wrapped in useCallback
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
      {/* 1. Full-Screen Interactive Weather Map */}
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
        activeView={activeView}
        selectedStation={selectedStation}
      />

      {/* 2. Floating Top Navigation */}
      <TopBar
        onSelectLocation={handleSelectLocation}
        showWebcams={showWebcams}
        onToggleWebcams={() => setShowWebcams(!showWebcams)}
        onSelectAnomalies={() => {
          setActiveLayer(activeLayer === 'anomalies' ? 'none' : 'anomalies');
          setActiveView(activeLayer === 'anomalies' ? 'overview' : 'anomalies');
        }}
        isAnomalyActive={activeLayer === 'anomalies' || activeView === 'anomalies'}
        unitSystem={unitSystem}
        onToggleUnitSystem={() =>
          setUnitSystem(unitSystem === 'metric' ? 'imperial' : 'metric')
        }
        particleDensity={particleDensity}
        onDensityChange={setParticleDensity}
        speedMultiplier={speedMultiplier}
        onSpeedChange={setSpeedMultiplier}
      />

      {/* 3. SIH Command Center Sidebar */}
      <CommandSidebar 
        activeLayer={activeLayer} 
        isAnomalyActive={activeLayer === 'anomalies'} 
        onSelectAnomalies={() => { 
          setActiveLayer(activeLayer === 'anomalies' ? 'none' : 'anomalies'); 
        }} 
        onSelectLayer={(layer) => { 
          setActiveLayer(layer); 
          if (layer !== 'anomalies') { 
            setSelectedStation(null); 
          } 
        }} 
        activeView={activeView}
        onViewChange={(view) => {
          setActiveView(view);
          // Smart layer toggling based on view
          if (view === 'anomalies') {
            setActiveLayer('anomalies');
          } else if (view === 'overview' && activeLayer === 'anomalies') {
            setActiveLayer('none');
          }
        }}
      /> 

      {/* 4. Right Side Dynamic Panels */}
      {/* Show LiveAlertPanel for Overview, Stations, and Anomalies */}
      {/* 4. Right Side Dynamic Panels */}
      
      {/* Overview View: Deliberately empty! Shows the full edge-to-edge map without a right panel */}
      
      {/* Anomalies Panel */}
      {activeView === 'anomalies' && (
        <LiveAlertPanel 
          onSelectStation={(station) => { 
            handleSelectStation({ 
              id: station.station_id, 
              stationName: station.name, 
              state: '', 
              lat: station.lat, 
              lon: station.lon, 
              severity: 'D3' as any, 
              severityLabel: 'Anomaly', 
              status: 'Critical' as any, 
              anomalyType: 'Heatwave Spike' as any, 
              confidenceScore: station.anomaly?.confidence_score || 0, 
              soilMoistureIndex: 0, 
              heatAnomalyDelta: station.weather?.temperature_c || 0, 
              rainfallDeficitPercent: 0, 
              aiRecommendation: station.anomaly?.explanation || '', 
              lastUpdated: station.timestamp, 
            }); 
          }} 
        />
      )}

      {/* Stations Panel */}
      {activeView === 'stations' && (
        <StationsPanel 
          onSelectStation={(station) => { 
            handleSelectStation({ 
              id: station.station_id, 
              stationName: station.name || station.station_id, 
              state: '', 
              lat: station.lat, 
              lon: station.lon, 
              severity: (station.anomaly?.confidence_score >= 0.8 ? 'D4' : station.anomaly?.is_anomaly ? 'D3' : 'D1') as any,
              severityLabel: station.anomaly?.is_anomaly ? 'Anomaly' : 'Healthy', 
              status: (station.anomaly?.confidence_score >= 0.8 ? 'Critical' : station.anomaly?.is_anomaly ? 'Warning' : 'Active') as any,
              anomalyType: (station.anomaly?.root_cause || 'None') as any, 
              confidenceScore: station.anomaly?.confidence_score || 0, 
              soilMoistureIndex: 0, 
              heatAnomalyDelta: station.weather?.temperature_c || 0, 
              rainfallDeficitPercent: 0, 
              aiRecommendation: station.anomaly?.explanation || 'Operating normally.', 
              lastUpdated: station.timestamp, 
            }); 
          }} 
        />
      )}
      {/* Placeholder Panel for AI Insights */}
      {activeView === 'ai-insights' && <AiInsights />}

      {/* Placeholder Panel for Self-Healing */}
      {activeView === 'self-healing'&& <SelfHealingPanel/>}

      {/* Placeholder Panel for Analytics */}
      {activeView === 'analytics' && < AnalyticsPanel/>}

      {/* 5. Dismissible Compact Weather Info Panel */}
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

      {/* 6. Altitude Selector */}
      {activeLayer === 'wind' && (
        <AltitudeSlider
          altitude={altitude}
          onSelectAltitude={setAltitude}
        />
      )}

      {/* 7. Dynamic Color Scale Legend */}
      {activeLayer !== 'none' && activeLayer !== 'anomalies' && (
        <ColorScaleLegend
          layer={activeLayer}
          unitSystem={unitSystem}
        />
      )}

      {/* 8. Windy-Style Floating Forecast Timeline */}
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

      {/* 9. Live Webcam Stream Modal */}
      <WebcamModal
        webcam={selectedWebcam}
        onClose={() => setSelectedWebcam(null)}
      />
    </div>
  );
}

export default App;