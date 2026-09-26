import React from 'react';

/**
 * Compact meteorological-station marker for INDIVIDUAL stations (clusters keep
 * their own native count marker).
 *
 * Recreates the geometry of the green.png / red.png references as sharp
 * vector UI instead of a raster: a bell-shaped station body on a thin mast,
 * with a two-cup anemometer rotor on top and a ground-plane radar underneath.
 *
 * ANIMATION (all CSS, no JS loops - see the `.ws-*` rules in index.css):
 *   - `.ws-rotor` (arm + both cups) spins around the mast's vertical axis. It
 *     lives in a plane tilted with `rotateX()`, so the arm sweeps the ellipse a
 *     real rotor does when seen from slightly above. Only this element turns;
 *     the mast, body and radar are separate, static elements.
 *   - `.ws-ring` (x2) expand-and-fade and `.ws-sweep` rotates slowly, both
 *     squashed onto the ground plane and centred on the station's foot.
 *
 * GEOGRAPHIC ANCHOR: the station's foot (bottom-centre of the body, which is
 * also the centre of the radar) is the marker's anchor point. The host element
 * handed to maplibregl.Marker has zero size, so the foot sits exactly on the
 * station's coordinates (see StationMarkerLayer.tsx).
 *
 * CLUSTERS: the SAME AWS marker is used for a cluster of stations; the only difference is
 * a small neutral count badge above it (`count > 1`). There is no circle: the marker is the
 * cluster, the badge is just its label. For a cluster, `status` is the highest severity of
 * the stations it contains (anomaly > warning > normal); each station keeps its own colour
 * once the cluster expands.
 *
 * STATUS -> LOOK (existing statuses only; nothing new is invented):
 *   normal  -> green  (--status-normal)
 *   warning -> amber  (--status-warning)
 *   anomaly -> red    (--status-anomaly)
 *   offline -> muted grey, rotor and radar stopped (an existing station state
 *              that the previous circle markers also drew in grey)
 */
export type WeatherStationStatus = 'normal' | 'warning' | 'anomaly' | 'offline';

/** Maps the backend's existing status strings (NORMAL / WARNING / ANOMALY /
 * OFFLINE, any case) to the marker variant. Unknown values render as offline. */
export function toMarkerStatus(raw: unknown): WeatherStationStatus {
  switch (String(raw ?? '').toUpperCase()) {
    case 'NORMAL':
      return 'normal';
    case 'WARNING':
      return 'warning';
    case 'ANOMALY':
      return 'anomaly';
    default:
      return 'offline';
  }
}

/** Stable per-station animation phase (ms) so markers don't all pulse in sync.
 * Pure string hash - computed once per render, not an animation loop. */
function phaseFor(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return Math.abs(h) % 2400;
}

interface WeatherStationMarkerProps {
  status: WeatherStationStatus;
  selected?: boolean;
  /** Used for the tooltip / accessible name and to de-synchronise animations. */
  name?: string;
  seed?: string;
  /** false hides the radar (rings + sweep) for this marker; the rotor is unaffected. */
  radar?: boolean;
  /** Number of stations this marker represents. Only a value > 1 shows the badge
   * (a single station never shows "1"). */
  count?: number;
  /** Compact text for the badge (e.g. "1.2k"); defaults to the count. */
  countLabel?: string;
  /** Tooltip / accessible name override (used for clusters: breakdown by status). */
  label?: string;
  /** One of the 3 nearest stations of the selected station: a thin highlight ring on the ground. */
  neighbor?: boolean;
  onSelect?: () => void;
}

const STATUS_LABEL: Record<WeatherStationStatus, string> = {
  normal: 'Normal',
  warning: 'Warning',
  anomaly: 'Anomaly',
  offline: 'Offline',
};

const WeatherStationMarkerBase: React.FC<WeatherStationMarkerProps> = ({
  status,
  selected = false,
  name,
  seed,
  radar = true,
  count,
  countLabel,
  label: labelOverride,
  neighbor = false,
  onSelect,
}) => {
  const isCluster = (count ?? 1) > 1;
  const label = labelOverride ?? `${name ?? 'Weather station'} — ${STATUS_LABEL[status]}`;
  const delay = -phaseFor(seed ?? name ?? '');

  return (
    <div
      className={`ws-marker ws-${status}${isCluster ? ' is-cluster' : ''}${selected ? ' is-selected' : ''}${neighbor ? ' is-neighbor' : ''}${radar ? '' : ' ws-no-radar'}`}
      style={{ '--ws-delay': `${delay}ms` } as React.CSSProperties}
      role="button"
      tabIndex={-1}
      aria-label={label}
      aria-pressed={selected}
      title={label}
      onClick={(e) => {
        e.stopPropagation();
        onSelect?.();
      }}
    >
      {/* Ground plane, centred on the station's foot: soft base glow + radar. */}
      <span className="ws-glow" aria-hidden="true" />
      <span className="ws-radar" aria-hidden="true">
        <i className="ws-ring ws-ring-a" />
        <i className="ws-ring ws-ring-b" />
        <i className="ws-sweep" />
      </span>

      {/* STATIONARY: bell body, status band, mast, hub. */}
      <svg className="ws-body" viewBox="0 0 44 44" width="44" height="44" aria-hidden="true" focusable="false">
        {/* invisible hit target: the glyph itself is thin */}
        <circle className="ws-hit" cx="22" cy="24" r="13" />
        {/* mast: dark underlay for contrast on satellite imagery, then the light line */}
        <path d="M22 11 V18" className="ws-outline-line" />
        <path d="M22 11 V18" className="ws-mast" />
        {/* bell-shaped body: carries the status colour */}
        <path
          className="ws-cone"
          d="M22 17 C21 20 18.5 27 15.6 36 L28.4 36 C25.5 27 23 20 22 17 Z"
        />
        {/* highlight + collar for form (white, static) */}
        <path className="ws-shine" d="M22 18.6 C21.2 21.4 19.3 27 17.4 33 L20.2 33 C21 28 21.7 22.4 22 18.6 Z" />
        <path className="ws-band" d="M17.1 30.6 L26.9 30.6 L27.4 32.2 L16.6 32.2 Z" />
        {/* fixed hub the rotor turns on */}
        <circle className="ws-hub-static" cx="22" cy="11" r="2.1" />
      </svg>

      {/* ROTATING: horizontal arm + left cup + right cup. */}
      <div className="ws-rotor" aria-hidden="true">
        <svg viewBox="0 0 44 22" width="44" height="22" focusable="false">
          <path d="M8.5 11 H35.5" className="ws-outline-line" />
          <path d="M8.5 11 H35.5" className="ws-arm" />
          <circle className="ws-cup" cx="7.6" cy="11" r="3.5" />
          <circle className="ws-cup-dot" cx="7.6" cy="11" r="1.3" />
          <circle className="ws-cup" cx="36.4" cy="11" r="3.5" />
          <circle className="ws-hub" cx="22" cy="11" r="1.9" />
        </svg>
      </div>

      {/* Cluster label: a small neutral badge above the AWS icon, only for count > 1. */}
      {isCluster && (
        <span className="ws-count" aria-hidden="true">
          {countLabel ?? count}
        </span>
      )}
    </div>
  );
};

export const WeatherStationMarker = React.memo(WeatherStationMarkerBase);
