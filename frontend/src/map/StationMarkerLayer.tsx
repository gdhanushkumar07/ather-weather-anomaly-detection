import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import maplibregl from 'maplibre-gl';

import { STATIONS_SOURCE_ID, setDomMarkedStations, setSelectedHaloSuppressed } from './StationLayer';
import { WeatherStationMarker, WeatherStationStatus, toMarkerStatus } from './WeatherStationMarker';

/**
 * Draws BOTH kinds of station objects as weather-station markers:
 *
 *   INDIVIDUAL STATION  -> the AWS marker in its own status colour. No circle, no count.
 *   STATION CLUSTER     -> the same AWS marker with a small neutral count badge above it.
 *                          Its colour is the highest severity inside it
 *                          (anomaly > warning > normal); no circle, no big background.
 *
 * Where the hierarchy comes from (nothing is hard-coded): MapLibre's own GeoJSON clustering
 * (supercluster) on the station source, configured in StationLayer.ts. At every zoom it
 * returns, from the stations' coordinates alone, either an individual point or a cluster
 * with its exact `point_count`; as the zoom grows, clusters split into smaller clusters and
 * finally into individual stations (no clusters above `clusterMaxZoom`). This layer only
 * asks the source what exists in the current view (`querySourceFeatures`) and mounts one
 * `maplibregl.Marker` per result, so cluster counts are the clustering library's real
 * counts, and a cluster that splits shows the children's real counts.
 *
 * Positioning is MapLibre's own (a Marker re-projects on every move/zoom/rotate/pitch,
 * globe included; markers on the far side of the planet are hidden via `opacityWhenCovered`).
 * The host is 0x0, so the marker's foot is exactly on the coordinates (a cluster's are the
 * centroid of its stations).
 *
 * No JavaScript animation: the rotor and radar are CSS keyframes (index.css). JS runs only
 * when the visible set can have changed (moveend / idle / source data), debounced, and it is
 * skipped while the source is still loading so markers never blink out mid-zoom.
 *
 * Bounded cost: at most MAX_DOM_MARKERS objects exist at once (clusters first, then nearest
 * to the view centre; the selected station is always kept). At low zoom that is a handful of
 * clusters; individual stations only appear once the clustering has split them apart.
 */
const MAX_DOM_MARKERS = 900;
const DENSE_THRESHOLD = 150;       // calm radar off beyond this many markers
const VERY_DENSE_THRESHOLD = 400;  // all radar off (except the selected station)
const REFRESH_DEBOUNCE_MS = 80;
const VIEWPORT_PAD_PX = 60;
const CLUSTER_EXPAND_EXTRA_ZOOM = 0.6; // same feel as the previous click-to-zoom

type MarkerKind = 'station' | 'cluster';

interface MarkerEntry {
  key: string;                 // 's:<station id>' | 'c:<cluster id>'
  kind: MarkerKind;
  stationId?: string;
  clusterId?: number;
  name: string;
  status: WeatherStationStatus;
  count: number;
  countLabel?: string;
  label?: string;              // tooltip / accessible name (clusters: status breakdown)
  lngLat: [number, number];
  marker: maplibregl.Marker;
  el: HTMLDivElement;
}

interface StationMarkerLayerProps {
  map: maplibregl.Map;
  /** Map Options -> AWS stations toggle. When false every DOM marker is removed. */
  visible: boolean;
  selectedStationId: string | null;
  onSelectStation: (stationId: string) => void;
  /** Map Options -> Anomaly Overlay: whether anomaly markers show their radar. */
  showAnomalyRadar?: boolean;
  /** Ids of the selected station's nearest neighbours (highlighted on their markers). */
  neighborIds?: string[];
  /** Changes whenever the station data is replaced, to trigger a refresh. */
  dataVersion?: unknown;
}

const Z_BY_STATUS: Record<WeatherStationStatus, number> = { offline: 0, normal: 1, warning: 2, anomaly: 3 };

/** Highest severity present in a cluster: ANOMALY > WARNING > NORMAL (else offline). */
function clusterStatus(anomalies: number, warnings: number, normals: number): WeatherStationStatus {
  if (anomalies > 0) return 'anomaly';
  if (warnings > 0) return 'warning';
  if (normals > 0) return 'normal';
  return 'offline';
}

export const StationMarkerLayer: React.FC<StationMarkerLayerProps> = ({
  map,
  visible,
  selectedStationId,
  onSelectStation,
  showAnomalyRadar = true,
  neighborIds,
  dataVersion,
}) => {
  const entriesRef = useRef<Map<string, MarkerEntry>>(new Map());
  const [, setRenderTick] = useState(0);
  const markedKeyRef = useRef<string>('');
  const timerRef = useRef<number | undefined>(undefined);

  // Always-current values for the long-lived map listeners below.
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const selectedRef = useRef(selectedStationId);
  selectedRef.current = selectedStationId;
  const onSelectRef = useRef(onSelectStation);
  onSelectRef.current = onSelectStation;

  const applyHalo = useCallback(() => {
    const id = selectedRef.current;
    setSelectedHaloSuppressed(map, !!id && entriesRef.current.has(`s:${id}`));
  }, [map]);

  const removeAll = useCallback(() => {
    entriesRef.current.forEach((e) => e.marker.remove());
    const hadAny = entriesRef.current.size > 0;
    entriesRef.current.clear();
    markedKeyRef.current = '';
    map.getContainer().classList.remove('ws-dense', 'ws-very-dense');
    setDomMarkedStations(map, []);
    setSelectedHaloSuppressed(map, false);
    if (hadAny) setRenderTick((t) => t + 1);
  }, [map]);

  /** Clicking a cluster zooms to the level at which it splits (MapLibre computes it). */
  const expandCluster = useCallback((clusterId: number, lngLat: [number, number]) => {
    const source = map.getSource(STATIONS_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    source.getClusterExpansionZoom(clusterId).then((zoom) => {
      map.easeTo({ center: lngLat, zoom: zoom + CLUSTER_EXPAND_EXTRA_ZOOM, duration: 450 });
    });
  }, [map]);

  const refresh = useCallback(() => {
    if (!visibleRef.current || !map.getSource(STATIONS_SOURCE_ID)) {
      if (entriesRef.current.size) removeAll();
      return;
    }
    // While the source is still (re)building tiles for the new zoom, keep what is on screen:
    // querying now would return a partial set and markers would blink out and back.
    if (!map.isSourceLoaded(STATIONS_SOURCE_ID)) return;

    const canvas = map.getCanvas();
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    // The map is kept mounted but hidden (display:none) while another workspace is active;
    // a 0x0 canvas would cull everything, so leave the markers as they are.
    if (w === 0 || h === 0) return;

    // Everything the clustering currently produces: individual points AND clusters.
    // (Deduplicated: a feature can be returned once per overlapping tile.)
    const features = map.querySourceFeatures(STATIONS_SOURCE_ID);
    const centerLng = map.getCenter().lng;
    // Tiles near the antimeridian also carry a copy of a feature shifted by 360 degrees
    // (and a copy of a cluster gets a DIFFERENT cluster id). Normalise the longitude so the
    // copies are recognised as one object, and keep the copy nearest the view centre.
    const wrap180 = (lng: number) => ((((lng + 180) % 360) + 360) % 360) - 180;

    interface Candidate {
      key: string; kind: MarkerKind; stationId?: string; clusterId?: number; name: string;
      status: WeatherStationStatus; count: number; countLabel?: string; label?: string;
      lngLat: [number, number]; d2: number;
    }
    const wanted = new Map<string, Candidate>();
    for (const f of features) {
      if (f.geometry.type !== 'Point') continue;
      const props: any = f.properties || {};
      const isCluster = props.cluster === true || props.point_count !== undefined;
      if (!isCluster && !props.id) continue;
      const lngLat = f.geometry.coordinates as [number, number];
      const key = isCluster
        ? `c:${props.point_count}:${wrap180(lngLat[0]).toFixed(3)}:${lngLat[1].toFixed(3)}`
        : `s:${props.id}`;
      const previous = wanted.get(key);
      if (previous && Math.abs(previous.lngLat[0] - centerLng) <= Math.abs(lngLat[0] - centerLng)) continue;
      const p = map.project(lngLat);
      if (p.x < -VIEWPORT_PAD_PX || p.x > w + VIEWPORT_PAD_PX || p.y < -VIEWPORT_PAD_PX || p.y > h + VIEWPORT_PAD_PX) continue;
      const d2 = (p.x - w / 2) ** 2 + (p.y - h / 2) ** 2;

      if (isCluster) {
        const count = Number(props.point_count) || 0;
        const a = Number(props.anomalies) || 0;
        const wa = Number(props.warnings) || 0;
        const nm = Number(props.normals) || 0;
        const other = Math.max(0, count - a - wa - nm);
        wanted.set(key, {
          key, kind: 'cluster', clusterId: Number(props.cluster_id), name: `${count} stations`,
          status: clusterStatus(a, wa, nm), count, countLabel: String(props.point_count_abbreviated ?? count),
          label: `${count} stations — ${a} anomaly, ${wa} warning, ${nm} normal${other ? `, ${other} offline` : ''} (click to expand)`,
          lngLat, d2,
        });
      } else {
        wanted.set(key, {
          key, kind: 'station', stationId: String(props.id), name: String(props.name ?? props.id),
          status: toMarkerStatus(props.status), count: 1, lngLat, d2,
        });
      }
    }

    let list = Array.from(wanted.values());
    if (list.length > MAX_DOM_MARKERS) {
      const sel = selectedRef.current ? `s:${selectedRef.current}` : '';
      const rank = (c: Candidate) => (c.key === sel ? 0 : c.kind === 'cluster' ? 1 : 2);
      list.sort((a, b) => rank(a) - rank(b) || a.d2 - b.d2);
      list = list.slice(0, MAX_DOM_MARKERS);
    }
    const keep = new Set(list.map((c) => c.key));

    let changed = false;
    entriesRef.current.forEach((entry, key) => {
      if (!keep.has(key)) {
        entry.marker.remove();
        entriesRef.current.delete(key);
        changed = true;
      }
    });

    for (const c of list) {
      const existing = entriesRef.current.get(c.key);
      if (existing) {
        if (existing.status !== c.status || existing.name !== c.name || existing.count !== c.count || existing.label !== c.label) {
          existing.status = c.status; existing.name = c.name; existing.count = c.count;
          existing.countLabel = c.countLabel; existing.label = c.label;
          existing.el.style.zIndex = String(Z_BY_STATUS[c.status]);
          changed = true;
        }
        continue;
      }
      // Zero-size host => the marker's foot is exactly at the coordinates.
      const el = document.createElement('div');
      el.className = 'ws-marker-host';
      el.style.zIndex = String(Z_BY_STATUS[c.status]);
      const marker = new maplibregl.Marker({
        element: el,
        anchor: 'center',
        pitchAlignment: 'viewport',
        rotationAlignment: 'viewport',
        opacityWhenCovered: '0', // hidden when on the far side of the globe
      })
        .setLngLat(c.lngLat)
        .addTo(map);
      entriesRef.current.set(c.key, {
        key: c.key, kind: c.kind, stationId: c.stationId, clusterId: c.clusterId, name: c.name, status: c.status,
        count: c.count, countLabel: c.countLabel, label: c.label, lngLat: c.lngLat, marker, el,
      });
      changed = true;
    }

    // Density classes on the map container (one class toggle, not per marker).
    const n = entriesRef.current.size;
    const container = map.getContainer();
    container.classList.toggle('ws-dense', n >= DENSE_THRESHOLD);
    container.classList.toggle('ws-very-dense', n >= VERY_DENSE_THRESHOLD);
    container.style.setProperty('--ws-zoom', String(zoomScale(map.getZoom())));

    // Native fallback circles only for INDIVIDUAL stations that have no DOM marker.
    const ids: string[] = [];
    entriesRef.current.forEach((e) => { if (e.kind === 'station' && e.stationId) ids.push(e.stationId); });
    ids.sort();
    const key = ids.join('|');
    if (key !== markedKeyRef.current) {
      markedKeyRef.current = key;
      setDomMarkedStations(map, ids);
    }
    applyHalo();

    if (changed) setRenderTick((t) => t + 1);
  }, [map, removeAll, applyHalo]);

  const scheduleRefresh = useCallback(() => {
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(refresh, REFRESH_DEBOUNCE_MS);
  }, [refresh]);

  // Map listeners: the visible set can only change when the camera settles, when the
  // source's data/tiles change, or when the map goes idle.
  useEffect(() => {
    const onSourceData = (e: any) => {
      if (e.sourceId === STATIONS_SOURCE_ID && e.isSourceLoaded) scheduleRefresh();
    };
    map.on('moveend', scheduleRefresh);
    map.on('idle', scheduleRefresh);
    map.on('sourcedata', onSourceData);
    refresh();
    return () => {
      map.off('moveend', scheduleRefresh);
      map.off('idle', scheduleRefresh);
      map.off('sourcedata', onSourceData);
      window.clearTimeout(timerRef.current);
      removeAll(); // restores the native fallback circles
    };
  }, [map, refresh, scheduleRefresh, removeAll]);

  // Station toggle / new data / selection.
  useEffect(() => { scheduleRefresh(); }, [visible, dataVersion, scheduleRefresh]);
  useEffect(() => {
    entriesRef.current.forEach((e) => {
      const selected = e.kind === 'station' && e.stationId === selectedStationId;
      e.el.style.zIndex = String(selected ? 10 : Z_BY_STATUS[e.status]);
    });
    applyHalo();
    if (selectedStationId) scheduleRefresh(); // keep the selected station within the cap
  }, [selectedStationId, applyHalo, scheduleRefresh]);

  const neighborSet = new Set(neighborIds ?? []);

  return (
    <>
      {Array.from(entriesRef.current.values()).map((e) =>
        createPortal(
          <WeatherStationMarker
            status={e.status}
            selected={e.kind === 'station' && e.stationId === selectedStationId}
            name={e.name}
            seed={e.key}
            count={e.kind === 'cluster' ? e.count : undefined}
            countLabel={e.countLabel}
            label={e.label}
            neighbor={e.kind === 'station' && !!e.stationId && neighborSet.has(e.stationId)}
            radar={e.status !== 'anomaly' || showAnomalyRadar || (e.kind === 'station' && e.stationId === selectedStationId)}
            onSelect={() => {
              if (e.kind === 'cluster' && e.clusterId !== undefined) expandCluster(e.clusterId, e.lngLat);
              else if (e.stationId) onSelectRef.current(e.stationId);
            }}
          />,
          e.el,
          e.key
        )
      )}
    </>
  );
};

/** Slightly smaller markers when the whole network is in view, full size up close. */
function zoomScale(zoom: number): number {
  if (zoom < 3.5) return 0.8;
  if (zoom < 6.5) return 0.95;
  return 1.1;
}
