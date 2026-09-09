import React, { useEffect, useState } from 'react';
import type { Map as LeafletMap } from 'leaflet';
import L from 'leaflet';
import type { WebcamItem } from '../../types/weather';
import { fetchWebcams } from '../../utils/api';

interface WebcamMarkersProps {
  map: LeafletMap | null;
  visible: boolean;
  onSelectWebcam: (webcam: WebcamItem) => void;
}

export const WebcamMarkers: React.FC<WebcamMarkersProps> = ({
  map,
  visible,
  onSelectWebcam,
}) => {
  const [webcams, setWebcams] = useState<WebcamItem[]>([]);
  const layerGroupRef = React.useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    fetchWebcams(19.076, 72.8777)
      .then((cams) => setWebcams(cams))
      .catch((err) => console.warn('Could not load webcams:', err));
  }, []);

  useEffect(() => {
    if (!map) return;

    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup().addTo(map);
    }

    const lg = layerGroupRef.current;
    lg.clearLayers();

    if (!visible) return;

    webcams.forEach((cam) => {
      const iconHtml = `
        <div class="relative flex items-center justify-center cursor-pointer group">
          <div class="w-6 h-6 rounded-full bg-blue-500/80 border border-white flex items-center justify-center text-white shadow-lg transform transition-transform group-hover:scale-125">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
              <circle cx="12" cy="13" r="3"/>
            </svg>
          </div>
          <div class="absolute -top-7 px-2 py-0.5 rounded bg-slate-900/90 text-white text-[10px] font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none border border-white/10 shadow-md">
            📷 ${cam.title}
          </div>
        </div>
      `;

      const markerIcon = L.divIcon({
        html: iconHtml,
        className: 'webcam-marker-icon',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const marker = L.marker([cam.lat, cam.lon], { icon: markerIcon });
      marker.on('click', () => {
        onSelectWebcam(cam);
      });

      marker.addTo(lg);
    });

    return () => {
      lg.clearLayers();
    };
  }, [map, visible, webcams, onSelectWebcam]);

  return null;
};
