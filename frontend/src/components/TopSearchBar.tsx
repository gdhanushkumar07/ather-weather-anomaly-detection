import React, { useState, useEffect, useRef } from 'react';
import { Search, MapPin, Navigation, X, Trophy } from 'lucide-react';
import { LocationCoords, WeatherLayer, TempUnit, WindSpeedUnit } from '../types';
import { searchCities } from '../utils/weatherApi';

interface TopSearchBarProps {
  onSelectLocation: (coords: LocationCoords) => void;
  onLocateMe: () => void;
  selectedLocationName: string;
  currentTemp?: number;
  tempUnit: TempUnit;
  onToggleTempUnit: () => void;
  onSelectLayer: (layer: WeatherLayer) => void;
  onOpenMenu: () => void;
}

export const TopSearchBar: React.FC<TopSearchBarProps> = ({
  onSelectLocation,
  onLocateMe,
  selectedLocationName,
  currentTemp = 8,
  tempUnit,
  onToggleTempUnit,
  onSelectLayer,
  onOpenMenu,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<LocationCoords[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const searchContainerRef = useRef<HTMLDivElement>(null);

  // Popular default cities for quick jump
  const popularCities: LocationCoords[] = [
    { name: 'Hyderabad', country: 'India', lat: 17.3850, lon: 78.4867, elevation: 542 },
    { name: 'Mumbai', country: 'India', lat: 19.0760, lon: 72.8777, elevation: 14 },
    { name: 'New Delhi', country: 'India', lat: 28.6139, lon: 77.2090, elevation: 216 },
    { name: 'Bengaluru', country: 'India', lat: 12.9716, lon: 77.5946, elevation: 920 },
    { name: 'London', country: 'United Kingdom', lat: 51.5074, lon: -0.1278, elevation: 25 },
    { name: 'Tokyo', country: 'Japan', lat: 35.6762, lon: 139.6503, elevation: 40 },
    { name: 'New York', country: 'United States', lat: 40.7128, lon: -74.0060, elevation: 10 },
    { name: 'Dubai', country: 'United Arab Emirates', lat: 25.2048, lon: 55.2708, elevation: 5 },
  ];

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setIsLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      const res = await searchCities(query);
      setResults(res);
      setIsLoading(false);
    }, 260);

    return () => clearTimeout(timer);
  }, [query]);

  // Click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (city: LocationCoords) => {
    onSelectLocation(city);
    setQuery(city.name || '');
    setIsOpen(false);
  };

  return (
    <header className="fixed top-3 left-0 right-0 z-[1000] px-3 pointer-events-none flex items-center justify-between">
      {/* Top Left: Floating Rounded Pill Search Input with Locate Crosshair */}
      <div ref={searchContainerRef} className="relative w-60 sm:w-72 pointer-events-auto">
        <div className="flex items-center bg-[#181d26]/85 hover:bg-[#181d26]/95 backdrop-blur-md text-white px-3.5 py-1.5 rounded-full border border-white/15 shadow-xl transition-all">
          <Search className="w-4 h-4 text-slate-400 mr-2 shrink-0" />
          <input
            id="city-search-input"
            type="text"
            className="bg-transparent border-none outline-none text-[13px] w-full placeholder:text-slate-400 text-slate-100 font-medium"
            placeholder={selectedLocationName ? `${selectedLocationName}` : 'Search location...'}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setIsOpen(true);
            }}
            onFocus={() => setIsOpen(true)}
          />
          {query ? (
            <button
              id="clear-search-btn"
              onClick={() => {
                setQuery('');
                setResults([]);
              }}
              className="text-slate-400 hover:text-white p-0.5 rounded cursor-pointer mr-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          ) : null}

          {/* Crosshair Locate Button right inside the search pill */}
          <button
            id="locate-me-btn"
            onClick={onLocateMe}
            title="Locate my position"
            className="text-slate-400 hover:text-sky-400 p-0.5 transition-colors cursor-pointer shrink-0 ml-1"
          >
            <Navigation className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Dropdown search results */}
        {isOpen && (
          <div className="absolute top-full left-0 mt-2 w-full bg-[#181d26]/95 backdrop-blur-xl border border-white/15 rounded-2xl shadow-2xl overflow-hidden z-[1050] max-h-[380px] overflow-y-auto">
            {isLoading && (
              <div className="p-3 text-xs text-slate-400 flex items-center justify-center gap-2">
                <div className="w-3.5 h-3.5 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
                Searching forecast locations...
              </div>
            )}

            {!isLoading && results.length > 0 && (
              <div className="py-1">
                {results.map((loc, idx) => (
                  <button
                    key={`res-${idx}`}
                    id={`search-result-${idx}`}
                    onClick={() => handleSelect(loc)}
                    className="w-full text-left px-3.5 py-2 text-xs hover:bg-white/10 flex items-center justify-between transition-colors border-b border-white/5 cursor-pointer"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <MapPin className="w-3.5 h-3.5 text-[#e5283c] shrink-0" />
                      <span className="font-semibold text-slate-100">{loc.name}</span>
                      <span className="text-slate-400 text-[11px] truncate">
                        {loc.admin1 ? `${loc.admin1}, ` : ''}{loc.country}
                      </span>
                    </div>
                    {loc.elevation !== undefined && (
                      <span className="text-[10px] text-slate-500 shrink-0 ml-2">{loc.elevation}m</span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {!isLoading && query.trim().length > 0 && results.length === 0 && (
              <div className="p-4 text-xs text-slate-400 text-center">
                No location found for "{query}".
              </div>
            )}

            {/* Popular cities */}
            {(!query || results.length === 0) && (
              <div className="py-1">
                <div className="px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-white/5">
                  Popular Locations
                </div>
                {popularCities.map((city, idx) => (
                  <button
                    key={`pop-${idx}`}
                    id={`popular-city-${idx}`}
                    onClick={() => handleSelect(city)}
                    className="w-full text-left px-3.5 py-2 text-xs hover:bg-white/10 flex items-center justify-between transition-colors border-b border-white/5 cursor-pointer"
                  >
                    <span className="font-medium text-slate-200">{city.name}, {city.country}</span>
                    <span className="text-[10px] text-slate-400">{city.lat.toFixed(1)}°, {city.lon.toFixed(1)}°</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Top Center: Subtle ATHER Logo/Title */}
      <div 
        id="ather-logo-badge"
        onClick={() => onSelectLayer('wind')}
        className="pointer-events-auto hidden sm:flex items-center gap-2 bg-[#181d26]/85 hover:bg-[#202735] backdrop-blur-md border border-white/10 text-white px-3.5 py-1.5 rounded-full shadow-xl cursor-pointer select-none transition-all active:scale-95"
        title="ATHER - Meteorological & Anomaly Detection Dashboard"
      >
        <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-sky-500 via-indigo-500 to-amber-400 flex items-center justify-center text-[10px] shadow-sm">
          🛡️
        </div>
        <span className="font-bold tracking-tight text-sm text-slate-100 flex items-center gap-1.5">
          <span>ATHER</span>
        </span>
      </div>

      {/* Top Right: Temperature + Avatar + Menu Hamburger */}
      <div className="pointer-events-auto flex items-center gap-2 sm:gap-2.5">
        {/* Weather Readout */}
        <button
          id="top-weather-temp-btn"
          onClick={onToggleTempUnit}
          className="hidden md:flex items-center gap-1.5 bg-[#181d26]/85 hover:bg-[#202735] backdrop-blur-md px-3 py-1.5 rounded-full border border-white/10 text-xs font-semibold text-slate-200 hover:text-white shadow-lg cursor-pointer transition-colors"
          title="Toggle Temperature Unit"
        >
          <span className="text-amber-400">☀️</span>
          <span>{currentTemp}°{tempUnit.toUpperCase()}</span>
        </button>

        {/* User Avatar Circle */}
        <div
          id="user-avatar-badge"
          className="w-8 h-8 rounded-full bg-gradient-to-tr from-purple-700 to-indigo-600 border border-white/20 flex items-center justify-center text-white font-bold text-xs shadow-lg cursor-pointer hover:ring-2 hover:ring-white/30 transition-all"
          title="Account Profile"
        >
          G
        </div>

        {/* Menu Button with Red Circular Hamburger */}
        <button
          id="top-menu-btn"
          onClick={onOpenMenu}
          className="flex items-center gap-2 bg-[#181d26]/85 hover:bg-[#202735] backdrop-blur-md text-white pl-3 pr-1.5 py-1.5 rounded-full border border-white/10 shadow-xl transition-all cursor-pointer select-none active:scale-95"
          title="Open ATHER settings menu"
        >
          <span className="text-xs font-semibold text-slate-200">Menu</span>
          <div className="w-6 h-6 rounded-full bg-[#e5283c] flex flex-col items-center justify-center gap-0.5 shadow-md">
            <div className="w-3 h-[2px] bg-white rounded-full" />
            <div className="w-3 h-[2px] bg-white rounded-full" />
            <div className="w-3 h-[2px] bg-white rounded-full" />
          </div>
        </button>
      </div>
    </header>
  );
};
