/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import L from 'leaflet';
import { 
  WeatherLayer, 
  WeatherModel, 
  MapBasemap, 
  LocationCoords, 
  PointForecastData, 
  WebcamItem, 
  AIAnomalyData, 
  WindSpeedUnit, 
  TempUnit, 
  PressureUnit,
  AltitudeLevel,
  StationType,
  AwsStation,
  AtherDemoScenario,
  AtherMapMode,
  GlobalWeatherStation,
  StationLiveWeather
} from './types';
import { MapContainer } from './components/MapContainer';
import { AtherTopBar } from './components/AtherTopBar';
import { LayerSwitcher } from './components/LayerSwitcher';
import { TimelineSlider } from './components/TimelineSlider';
import { BottomControlBar } from './components/BottomControlBar';
import { MeteogramPanel } from './components/MeteogramPanel';
import { WebcamModal } from './components/WebcamModal';
import { MenuDrawer } from './components/MenuDrawer';
import { InfoModal } from './components/InfoModal';
import { AtherStationDrawer } from './components/AtherStationDrawer';
import { GlobalStationDrawer } from './components/GlobalStationDrawer';
import { AtherArchitectureModal } from './components/AtherArchitectureModal';
import { fetchPointForecast, fetchWebcams, fetchAIAnomaly } from './utils/weatherApi';
import { buildAwsNetwork, applyDemoScenario, simulateIncomingPacket } from './utils/awsNetwork';
import { loadGlobalStations, fetchStationWeather } from './services/stationService';

export default function App() {
  const mapRef = useRef<L.Map | null>(null);

  // ATHER Engine & AWS Network State
  const [awsStations, setAwsStations] = useState<AwsStation[]>(() => {
    const network = buildAwsNetwork('hyd_spike');
    return applyDemoScenario(network, 'hyd_spike');
  });
  const [currentScenario, setCurrentScenario] = useState<AtherDemoScenario>('hyd_spike');
  const [selectedAwsStation, setSelectedAwsStation] = useState<AwsStation | null>(null);
  const [mapMode, setMapMode] = useState<AtherMapMode>('anomalies');
  const [isStreaming, setIsStreaming] = useState<boolean>(true);
  const [isArchitectureModalOpen, setIsArchitectureModalOpen] = useState<boolean>(false);

  // Layer & Map Viewport state (Default: 'temperature' to show atmospheric core field)
  const [activeLayer, setActiveLayer] = useState<WeatherLayer>('temperature');
  const [altitudeLevel, setAltitudeLevel] = useState<AltitudeLevel>('surface');
  const [basemap, setBasemap] = useState<MapBasemap>('dark');
  const [timeOffsetHours, setTimeOffsetHours] = useState<number>(0);
  const [selectedModel, setSelectedModel] = useState<WeatherModel>('ecmwf');
  const [particleDensity, setParticleDensity] = useState<number>(1.0);

  // Toggles
  const [showParticles, setShowParticles] = useState<boolean>(true);
  const [showPressureIsolines, setShowPressureIsolines] = useState<boolean>(true);
  const [showAwsStations, setShowAwsStations] = useState<boolean>(true);
  const [showAnomalyMarkers, setShowAnomalyMarkers] = useState<boolean>(true);
  const [showGlobalStations, setShowGlobalStations] = useState<boolean>(true);
  const [is3D, setIs3D] = useState<boolean>(false);
  const [stationType, setStationType] = useState<StationType | null>(null);

  // Global NOAA ISD Stations
  const [globalStations, setGlobalStations] = useState<GlobalWeatherStation[]>([]);
  const [selectedGlobalStation, setSelectedGlobalStation] = useState<GlobalWeatherStation | null>(null);
  const [globalStationWeather, setGlobalStationWeather] = useState<StationLiveWeather | null>(null);
  const [isGlobalStationLoading, setIsGlobalStationLoading] = useState<boolean>(false);
  const [globalStationError, setGlobalStationError] = useState<string | null>(null);

  // Modals & Drawers
  const [isMenuOpen, setIsMenuOpen] = useState<boolean>(false);
  const [isInfoOpen, setIsInfoOpen] = useState<boolean>(false);
  const [isPanelOpen, setIsPanelOpen] = useState<boolean>(false);

  // Units
  const [tempUnit, setTempUnit] = useState<TempUnit>('c');
  const [windUnit, setWindUnit] = useState<WindSpeedUnit>('kt');
  const [pressureUnit, setPressureUnit] = useState<PressureUnit>('hpa');

  // Selected Location & Forecast Data (null initially to show the complete world map)
  const [selectedLocation, setSelectedLocation] = useState<LocationCoords | null>(null);
  const [forecastData, setForecastData] = useState<PointForecastData | null>(null);
  const [anomalyData, setAnomalyData] = useState<AIAnomalyData | null>(null);
  const [isForecastLoading, setIsForecastLoading] = useState<boolean>(false);

  // Webcams
  const [showWebcams, setShowWebcams] = useState<boolean>(false);
  const [webcams, setWebcams] = useState<WebcamItem[]>([]);
  const [selectedWebcam, setSelectedWebcam] = useState<WebcamItem | null>(null);

  // Load forecast data
  const loadForecastForCoords = useCallback(async (coords: LocationCoords, model: WeatherModel) => {
    setIsForecastLoading(true);
    try {
      const data = await fetchPointForecast(coords.lat, coords.lon, model);
      if (coords.name) data.location.name = coords.name;
      if (coords.country) data.location.country = coords.country;
      setForecastData(data);

      const anomaly = await fetchAIAnomaly(coords.lat, coords.lon, data.current);
      setAnomalyData(anomaly);
    } catch (err) {
      console.error('Failed to load point forecast:', err);
    } finally {
      setIsForecastLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    if (selectedLocation) {
      loadForecastForCoords(selectedLocation, selectedModel);
    }
    fetchWebcams().then(setWebcams);
    loadGlobalStations().then((stations) => {
      setGlobalStations(stations);
    }).catch((err) => {
      console.error('ATHER: Failed to load global station dataset:', err);
    });
  }, []);

  // Reload when model changes
  useEffect(() => {
    if (selectedLocation) {
      loadForecastForCoords(selectedLocation, selectedModel);
    }
  }, [selectedModel]);

  // Handle Scenario Switch
  const handleSelectScenario = (scenario: AtherDemoScenario) => {
    setCurrentScenario(scenario);
    const updated = applyDemoScenario(awsStations, scenario);
    setAwsStations([...updated]);

    // Pan map to relevant station
    if (scenario === 'hyd_spike') {
      const hyd = updated.find((s) => s.id === 'AWS-HYD-001');
      if (hyd) {
        setSelectedAwsStation(hyd);
        mapRef.current?.flyTo([hyd.lat, hyd.lon], 7, { duration: 1.2 });
      }
    } else if (scenario === 'frozen_sensor') {
      const del = updated.find((s) => s.id === 'AWS-DEL-003');
      if (del) {
        setSelectedAwsStation(del);
        mapRef.current?.flyTo([del.lat, del.lon], 7, { duration: 1.2 });
      }
    } else if (scenario === 'sensor_drift') {
      const mum = updated.find((s) => s.id === 'AWS-BOM-002');
      if (mum) {
        setSelectedAwsStation(mum);
        mapRef.current?.flyTo([mum.lat, mum.lon], 7, { duration: 1.2 });
      }
    } else if (scenario === 'unphysical_combo') {
      const kol = updated.find((s) => s.id === 'AWS-CCU-006');
      if (kol) {
        setSelectedAwsStation(kol);
        mapRef.current?.flyTo([kol.lat, kol.lon], 7, { duration: 1.2 });
      }
    } else if (scenario === 'genuine_heatwave') {
      const hyd = updated.find((s) => s.id === 'AWS-HYD-001');
      if (hyd) {
        setSelectedAwsStation(hyd);
        mapRef.current?.flyTo([hyd.lat, hyd.lon], 7, { duration: 1.2 });
      }
    } else {
      const first = updated[0];
      if (first) {
        setSelectedAwsStation(first);
      }
      mapRef.current?.flyTo([21.5, 78.5], 5, { duration: 1.2 });
    }
  };

  // Real-time telemetry simulation streaming
  useEffect(() => {
    if (!isStreaming) return;

    const interval = setInterval(() => {
      setAwsStations((prev) => {
        const { updatedNetwork, updatedStation } = simulateIncomingPacket(prev);
        // If current drawer station was updated, keep drawer in sync
        if (selectedAwsStation && selectedAwsStation.id === updatedStation.id) {
          setSelectedAwsStation(updatedStation);
        }
        return [...updatedNetwork];
      });
    }, 3500);

    return () => clearInterval(interval);
  }, [isStreaming, selectedAwsStation]);

  const handleSelectLocation = (coords: LocationCoords) => {
    setSelectedLocation(coords);
    setIsPanelOpen(true);
    mapRef.current?.flyTo([coords.lat, coords.lon], 7, { duration: 1.2 });
    loadForecastForCoords(coords, selectedModel);
  };

  // --- Global NOAA Station Selection & Open-Meteo Weather Fetch ---

  const fetchGlobalStationWeatherData = async (station: GlobalWeatherStation) => {
    setIsGlobalStationLoading(true);
    setGlobalStationError(null);
    setGlobalStationWeather(null);
    try {
      const weather = await fetchStationWeather(station.id, station.lat, station.lon);
      setGlobalStationWeather(weather);
    } catch (err: any) {
      const msg = err?.message || 'Weather data unavailable';
      setGlobalStationError(msg);
      console.warn('ATHER: Open-Meteo station weather fetch failed:', msg);
    } finally {
      setIsGlobalStationLoading(false);
    }
  };

  const handleSelectGlobalStation = (station: GlobalWeatherStation) => {
    setSelectedGlobalStation(station);
    fetchGlobalStationWeatherData(station);
  };

  const handleRefreshGlobalStation = () => {
    if (selectedGlobalStation) {
      fetchGlobalStationWeatherData(selectedGlobalStation);
    }
  };

  const handleCloseGlobalStation = () => {
    setSelectedGlobalStation(null);
    setGlobalStationWeather(null);
    setGlobalStationError(null);
    setIsGlobalStationLoading(false);
  };

  // -----------------------------------------------------------

  const handleLocateMe = () => {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const userCoords: LocationCoords = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            name: 'My Current Location',
          };
          handleSelectLocation(userCoords);
        },
        (err) => {
          console.warn('Geolocation denied or unavailable:', err);
        },
        { timeout: 8000 }
      );
    }
  };

  const handleFocusCyclone = () => {
    mapRef.current?.flyTo([16.5, 86.0], 5, { duration: 1.4 });
    setActiveLayer('hurricane');
  };

  const handleToggleTempUnit = () => {
    setTempUnit((prev) => (prev === 'c' ? 'f' : 'c'));
  };

  const handleToggleWindUnit = () => {
    const units: WindSpeedUnit[] = ['kt', 'kmh', 'ms', 'mph'];
    const nextIdx = (units.indexOf(windUnit) + 1) % units.length;
    setWindUnit(units[nextIdx]);
  };

  const handleTogglePressureUnit = () => {
    const units: PressureUnit[] = ['hpa', 'inhg', 'mmhg'];
    const nextIdx = (units.indexOf(pressureUnit) + 1) % units.length;
    setPressureUnit(units[nextIdx]);
  };

  // Station counts and critical station alert for ATHER Map-First Intelligence
  const criticalStation = awsStations.find(
    (s) => s.latestAnalysis?.severity === 'Critical' || s.healthStatus === 'critical'
  ) || null;

  return (
    <div id="ather-app-root" className="relative w-screen h-screen overflow-hidden bg-[#12151b] font-sans select-none">
      {/* 1. Unified ATHER Top Navigation Bar, Mode Switcher & Map-First Alert */}
      <AtherTopBar
        onSelectLocation={handleSelectLocation}
        onLocateMe={handleLocateMe}
        selectedLocationName={selectedLocation?.name || ''}
        mapMode={mapMode}
        onSelectMapMode={setMapMode}
        isStreaming={isStreaming}
        onToggleStreaming={() => setIsStreaming(!isStreaming)}
        currentScenario={currentScenario}
        onSelectScenario={handleSelectScenario}
        criticalStation={criticalStation}
        onInvestigateStation={(st) => {
          setSelectedAwsStation(st);
          mapRef.current?.flyTo([st.lat, st.lon], 7.5, { duration: 1.2 });
        }}
        onOpenArchitectureModal={() => setIsArchitectureModalOpen(true)}
        onOpenMenu={() => setIsMenuOpen(true)}
        globalStations={globalStations}
        onSelectGlobalStation={handleSelectGlobalStation}
        onFlyToGlobalStation={(station) => {
          mapRef.current?.flyTo([station.lat, station.lon], 9, { duration: 1.2 });
        }}
      />

      {/* 2. Floating ATHER AWS Station Information Card */}
      <AtherStationDrawer
        station={selectedAwsStation}
        onClose={() => setSelectedAwsStation(null)}
        tempUnit={tempUnit}
        pressureUnit={pressureUnit}
        allStations={awsStations}
      />

      {/* 2b. Global NOAA ISD Weather Station Drawer — Open-Meteo live conditions */}
      <GlobalStationDrawer
        station={selectedGlobalStation}
        weather={globalStationWeather}
        isLoading={isGlobalStationLoading}
        error={globalStationError}
        onClose={handleCloseGlobalStation}
        onRefresh={handleRefreshGlobalStation}
        tempUnit={tempUnit}
        pressureUnit={pressureUnit}
        windUnit={windUnit}
      />

      {/* 3. Floating Right Layer Switcher with ATHER primary layers & map modes */}
      <LayerSwitcher
        activeLayer={activeLayer}
        onSelectLayer={(l) => setActiveLayer(l)}
        altitudeLevel={altitudeLevel}
        onSelectAltitude={setAltitudeLevel}
        showAwsStations={showAwsStations}
        onToggleAwsStations={() => setShowAwsStations(!showAwsStations)}
        mapMode={mapMode}
        onSelectMapMode={setMapMode}
      />

      {/* 5. Interactive Leaflet Map with Canvas Particle Streamlines, Isobars & AWS Markers */}
      <MapContainer
        mapRef={mapRef}
        activeLayer={activeLayer}
        timeOffsetHours={timeOffsetHours}
        selectedLocation={selectedLocation}
        onSelectLocation={handleSelectLocation}
        windUnit={windUnit}
        tempUnit={tempUnit}
        pressureUnit={pressureUnit}
        showWebcams={showWebcams}
        webcams={webcams}
        onSelectWebcam={setSelectedWebcam}
        basemap={basemap}
        particleDensity={particleDensity}
        altitudeLevel={altitudeLevel}
        showParticles={showParticles}
        showPressureIsolines={showPressureIsolines}
        is3D={is3D}
        stationType={stationType}
        showAwsStations={showAwsStations}
        showAnomalyMarkers={showAnomalyMarkers}
        awsStations={awsStations}
        selectedStation={selectedAwsStation}
        onSelectStation={(st) => setSelectedAwsStation(st)}
        mapMode={mapMode}
        showGlobalStations={showGlobalStations}
        globalStations={globalStations}
        selectedGlobalStation={selectedGlobalStation}
        onSelectGlobalStation={handleSelectGlobalStation}
      />

      {/* 6. Bottom Right Floating Control Bar */}
      <BottomControlBar
        onZoomIn={() => mapRef.current?.zoomIn()}
        onZoomOut={() => mapRef.current?.zoomOut()}
        is3D={is3D}
        onToggle3D={() => setIs3D(!is3D)}
        showParticles={showParticles}
        onToggleParticles={() => setShowParticles(!showParticles)}
        showPressureIsolines={showPressureIsolines}
        onTogglePressureIsolines={() => setShowPressureIsolines(!showPressureIsolines)}
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
        activeLayer={activeLayer}
        onSelectLayer={setActiveLayer}
        stationType={stationType}
        onSelectStationType={setStationType}
        onOpenInfo={() => setIsInfoOpen(true)}
        onFocusStorm={handleFocusCyclone}
        windUnit={windUnit}
        onToggleWindUnit={handleToggleWindUnit}
        tempUnit={tempUnit}
        onToggleTempUnit={handleToggleTempUnit}
      />

      {/* 7. Fixed Timeline Slider (16-Day Forecast Scrubber across screen bottom) */}
      <TimelineSlider
        currentHourOffset={timeOffsetHours}
        onChangeHourOffset={setTimeOffsetHours}
      />

      {/* 8. Meteogram & Point Forecast Drawer */}
      {isPanelOpen && (
        <MeteogramPanel
          data={forecastData}
          anomalyData={anomalyData}
          isLoading={isForecastLoading}
          onClose={() => setIsPanelOpen(false)}
          tempUnit={tempUnit}
          windUnit={windUnit}
          pressureUnit={pressureUnit}
        />
      )}

      {/* 9. Live Webcam Modal Preview */}
      <WebcamModal
        webcam={selectedWebcam}
        onClose={() => setSelectedWebcam(null)}
      />

      {/* 10. ATHER Slide-out Menu Drawer */}
      <MenuDrawer
        isOpen={isMenuOpen}
        onClose={() => setIsMenuOpen(false)}
        tempUnit={tempUnit}
        onToggleTempUnit={handleToggleTempUnit}
        windUnit={windUnit}
        onToggleWindUnit={handleToggleWindUnit}
        pressureUnit={pressureUnit}
        onTogglePressureUnit={handleTogglePressureUnit}
        basemap={basemap}
        onSelectBasemap={setBasemap}
        showWebcams={showWebcams}
        onToggleWebcams={() => setShowWebcams(!showWebcams)}
        particleDensity={particleDensity}
        onChangeParticleDensity={setParticleDensity}
      />

      {/* 11. Meteorological Info Modal */}
      <InfoModal
        isOpen={isInfoOpen}
        onClose={() => setIsInfoOpen(false)}
      />

      {/* 12. ATHER Architecture Explanation Modal */}
      <AtherArchitectureModal
        isOpen={isArchitectureModalOpen}
        onClose={() => setIsArchitectureModalOpen(false)}
      />
    </div>
  );
}
