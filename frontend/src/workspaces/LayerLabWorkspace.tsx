import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Atom, Gauge, Layers, BookOpen, AlertTriangle, CheckCircle2, XOctagon, Loader2, MapPin, Clock, History, RotateCcw } from 'lucide-react';
import { analyzeLayerLab, fetchLayerLabContext } from '../services/api';
import { LabAnalysis, LabContext, LabPreset } from '../types/layerLab';
import { JointStateChart } from '../components/layerlab/JointStateChart';
import { DiurnalChart } from '../components/layerlab/DiurnalChart';
import { FeatureEvidence, ModelGauge } from '../components/layerlab/EvidenceViews';
import { PhysicsChecklist, PinnPanel } from '../components/layerlab/PhysicsViews';
import { fmt, hhmm } from '../components/layerlab/chartKit';
import './LayerLab.css';

interface Props { stationsGeoJSON: GeoJSON.FeatureCollection | null }

interface LabStation { id: string; name: string; region: string; lat: number; lon: number; t?: number; p?: number; rh?: number; ts?: string }

type Tab = 'physics' | 'multivariate' | 'how';

const DEFAULT = { id: 'custom', name: 'Custom location', region: '', lat: 28.61, lon: 77.21 };

/** Open-Meteo `current.time` is UTC without an offset: "2026-09-26T13:00". */
function toInputUtc(ts?: string): string {
  const d = ts ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`) : new Date();
  if (Number.isNaN(d.getTime())) return new Date().toISOString().slice(0, 16);
  return d.toISOString().slice(0, 16);
}

const Slider: React.FC<{ label: string; unit: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void; hint?: string }> =
({ label, unit, min, max, step, value, onChange, hint }) => (
  <label className="ll-slider">
    <span className="ll-slider-head">
      <span>{label}</span>
      <span className="ll-slider-value">
        <input type="number" value={value} step={step} onChange={(e) => onChange(Number(e.target.value))} /> {unit}
      </span>
    </span>
    <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    {hint && <span className="ll-slider-hint">{hint}</span>}
  </label>
);

const PRESET_GROUPS: { title: string; expect: LabPreset['expect'][] }[] = [
  { title: 'Normal behaviour', expect: ['NORMAL'] },
  { title: 'Layer 3 · joint-state scenarios', expect: ['MULTIVARIATE', 'EVIDENCE'] },
  { title: 'Layer 1 · physics violations', expect: ['PHYSICS'] },
];

export const LayerLabWorkspace: React.FC<Props> = ({ stationsGeoJSON }) => {
  const stations: LabStation[] = useMemo(() => {
    const feats = stationsGeoJSON?.features ?? [];
    return feats
      .filter((f) => f.properties?.source === 'NWP_MODEL_REFERENCE' && f.properties?.temperature != null && f.geometry?.type === 'Point')
      .map((f) => {
        const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
        const p = f.properties as Record<string, any>;
        return { id: String(p.id), name: String(p.name ?? p.id), region: String(p.region ?? 'Other'), lat, lon,
                 t: p.temperature, p: p.pressure, rh: p.humidity, ts: p.timestamp };
      })
      .sort((a, b) => a.region.localeCompare(b.region) || a.name.localeCompare(b.name));
  }, [stationsGeoJSON]);
  const regions = useMemo(() => Array.from(new Set(stations.map((s) => s.region))), [stations]);

  const [stationId, setStationId] = useState<string>('custom');
  const [lat, setLat] = useState(DEFAULT.lat);
  const [lon, setLon] = useState(DEFAULT.lon);
  const [elevation, setElevation] = useState(0);
  const [time, setTime] = useState(() => toInputUtc());
  const [t, setT] = useState(30);
  const [rh, setRh] = useState(50);
  const [p, setP] = useState(1005);
  const [dewOverride, setDewOverride] = useState<number | null>(null);
  const [usePrev, setUsePrev] = useState(false);
  const [prev, setPrev] = useState({ temperature_c: 30, humidity_pct: 50, pressure_hpa: 1005, minutes_before: 60 });
  const [activePreset, setActivePreset] = useState<string | null>(null);

  const [ctx, setCtx] = useState<LabContext | null>(null);
  const [result, setResult] = useState<LabAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('multivariate');
  const initialised = useRef(false);
  // Only the newest request may update the view — an older response that
  // arrives late must never overwrite the analysis of the current inputs.
  const analysisSeq = useRef(0);
  const contextSeq = useRef(0);

  const loadStation = (s: LabStation) => {
    setStationId(s.id); setLat(s.lat); setLon(s.lon); setTime(toInputUtc(s.ts));
    if (s.t != null) setT(Math.round(s.t * 10) / 10);
    if (s.rh != null) setRh(Math.round(s.rh));
    if (s.p != null) setP(Math.round(s.p * 10) / 10);
    setDewOverride(null); setUsePrev(false); setActivePreset(null);
  };

  // First live Indian station (Delhi NCR if present) as the starting point.
  useEffect(() => {
    if (initialised.current || !stations.length) return;
    initialised.current = true;
    loadStation(stations.find((s) => /delhi/i.test(s.region)) ?? stations[0]);
  }, [stations]);

  const timestamp = `${time}:00Z`;

  // Context (reference climatology + presets) follows place and time.
  useEffect(() => {
    const id = setTimeout(() => {
      const seq = ++contextSeq.current;
      fetchLayerLabContext(lat, lon, timestamp)
        .then((c) => { if (seq === contextSeq.current) setCtx(c); })
        .catch((e) => { if (seq === contextSeq.current) setError(String(e.message ?? e)); });
    }, 350);
    return () => clearTimeout(id);
  }, [lat, lon, timestamp]);

  // Analysis follows every input change.
  useEffect(() => {
    const id = setTimeout(() => {
      const seq = ++analysisSeq.current;
      setLoading(true);
      analyzeLayerLab({
        latitude: lat, longitude: lon, elevation_m: elevation, timestamp,
        temperature_c: t, humidity_pct: rh, pressure_hpa: p, dew_point_c: dewOverride,
        previous: usePrev ? prev : null,
      }).then((r) => { if (seq === analysisSeq.current) { setResult(r); setError(null); } })
        .catch((e) => { if (seq === analysisSeq.current) setError(String(e.message ?? e)); })
        .finally(() => { if (seq === analysisSeq.current) setLoading(false); });
    }, 250);
    return () => clearTimeout(id);
  }, [lat, lon, elevation, timestamp, t, rh, p, dewOverride, usePrev, prev]);

  const applyPreset = (pr: LabPreset) => {
    setT(pr.reading.temperature_c); setRh(pr.reading.humidity_pct); setP(pr.reading.pressure_hpa);
    setDewOverride(pr.reading.dew_point_c ?? null); setActivePreset(pr.id);
    if (pr.expect === 'PHYSICS') setTab('physics');
    else if (pr.expect !== 'NORMAL') setTab('multivariate');
  };

  const onEdit = (fn: (v: number) => void) => (v: number) => { fn(v); setActivePreset(null); };

  const ph = result?.physics;
  const mv = result?.multivariate;
  const solarHour = result?.input.solar_hour ?? ctx?.solar_hour ?? 12;
  const istTime = useMemo(() => {
    const d = new Date(timestamp);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' });
  }, [timestamp]);

  return (
    <div className="layer-lab">
      <div className="workspace-page-header">
        <div className="workspace-page-title-group">
          <div className="workspace-page-icon-badge"><Atom className="w-4 h-4 text-cyan-300" /></div>
          <div>
            <div className="workspace-page-title">LAYER LAB</div>
            <div className="workspace-page-subtitle">
              How the Physics (Layer 1) and Multivariate (Layer 3) layers judge a reading — live engine, not a mock-up
            </div>
          </div>
        </div>
        {loading && <span className="ll-loading"><Loader2 size={14} className="ll-spin" /> analysing…</span>}
      </div>

      <div className="ll-layout">
        {/* ── Controls ─────────────────────────────────────────── */}
        <aside className="ll-controls section-card">
          <div className="ll-control-group">
            <div className="ll-group-title"><MapPin size={13} /> Station</div>
            <select value={stationId} onChange={(e) => {
              const s = stations.find((x) => x.id === e.target.value);
              if (s) loadStation(s); else setStationId('custom');
            }}>
              <option value="custom">Custom coordinates</option>
              {regions.map((r) => (
                <optgroup key={r} label={r}>
                  {stations.filter((s) => s.region === r).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </optgroup>
              ))}
            </select>
            {stationId === 'custom' && (
              <div className="ll-row">
                <label>Lat <input type="number" step="0.01" value={lat} onChange={(e) => setLat(Number(e.target.value))} /></label>
                <label>Lon <input type="number" step="0.01" value={lon} onChange={(e) => setLon(Number(e.target.value))} /></label>
              </div>
            )}
            {stationId !== 'custom' && (
              <button className="ll-link-btn" onClick={() => { const s = stations.find((x) => x.id === stationId); if (s) loadStation(s); }}>
                <RotateCcw size={12} /> reload this station's live values
              </button>
            )}
          </div>

          <div className="ll-control-group">
            <div className="ll-group-title"><Clock size={13} /> Observation time (UTC)</div>
            <input type="datetime-local" value={time} onChange={(e) => setTime(e.target.value)} />
            <div className="ll-slider-hint">IST {istTime} · local solar time {hhmm(solarHour)} — Layer 3 picks its season and time-of-day model from this, never from “now”.</div>
          </div>

          <div className="ll-control-group">
            <div className="ll-group-title"><Gauge size={13} /> Reading</div>
            <Slider label="Temperature" unit="°C" min={-10} max={55} step={0.1} value={t} onChange={onEdit(setT)} />
            <Slider label="Relative humidity" unit="%" min={0} max={110} step={1} value={rh} onChange={onEdit(setRh)}
                    hint="Above 100 % is allowed here so you can see the physics veto." />
            <Slider label="Pressure (sea level)" unit="hPa" min={940} max={1050} step={0.1} value={p} onChange={onEdit(setP)} />
            <Slider label="Station elevation" unit="m" min={0} max={3500} step={10} value={elevation} onChange={setElevation}
                    hint="Used by the hypsometric altitude check (applies above 50 m)." />
            <label className="ll-check-toggle">
              <input type="checkbox" checked={dewOverride !== null} onChange={(e) => setDewOverride(e.target.checked ? Math.round(t) : null)} />
              Sensor also reports a dew point
            </label>
            {dewOverride !== null && <Slider label="Reported dew point" unit="°C" min={-20} max={45} step={0.1} value={dewOverride} onChange={onEdit(setDewOverride)} />}
          </div>

          <div className="ll-control-group">
            <label className="ll-check-toggle">
              <input type="checkbox" checked={usePrev} onChange={(e) => {
                setUsePrev(e.target.checked);
                if (e.target.checked) setPrev({ temperature_c: t, humidity_pct: rh, pressure_hpa: p, minutes_before: 60 });
              }} />
              <History size={13} /> Include the previous reading
            </label>
            {usePrev && (
              <div className="ll-prev">
                <div className="ll-slider-hint">Adds rate-of-change features (per hour) — how the three variables moved together.</div>
                <div className="ll-row">
                  <label>T <input type="number" step="0.1" value={prev.temperature_c} onChange={(e) => setPrev({ ...prev, temperature_c: Number(e.target.value) })} /></label>
                  <label>RH <input type="number" step="1" value={prev.humidity_pct} onChange={(e) => setPrev({ ...prev, humidity_pct: Number(e.target.value) })} /></label>
                </div>
                <div className="ll-row">
                  <label>P <input type="number" step="0.1" value={prev.pressure_hpa} onChange={(e) => setPrev({ ...prev, pressure_hpa: Number(e.target.value) })} /></label>
                  <label>min before <input type="number" step="10" min={10} max={180} value={prev.minutes_before} onChange={(e) => setPrev({ ...prev, minutes_before: Number(e.target.value) })} /></label>
                </div>
              </div>
            )}
          </div>

          <div className="ll-control-group">
            <div className="ll-group-title"><Layers size={13} /> Scenarios for this place and time</div>
            {!ctx?.presets && <div className="ll-slider-hint">{ctx?.note ?? 'Loading station climatology…'}</div>}
            {ctx?.presets && PRESET_GROUPS.map((g) => (
              <div key={g.title} className="ll-preset-group">
                <div className="ll-preset-group-title">{g.title}</div>
                {ctx.presets!.filter((pr) => g.expect.includes(pr.expect)).map((pr) => (
                  <button key={pr.id} className={`ll-preset ${activePreset === pr.id ? 'active' : ''}`} onClick={() => applyPreset(pr)} title={pr.description}>
                    {pr.label}
                  </button>
                ))}
              </div>
            ))}
            {activePreset && ctx?.presets && (
              <div className="ll-preset-desc">{ctx.presets.find((x) => x.id === activePreset)?.description}</div>
            )}
          </div>
        </aside>

        {/* ── Results ─────────────────────────────────────────── */}
        <section className="ll-main">
          {error && <div className="ll-error"><AlertTriangle size={14} /> {error}</div>}

          <div className="ll-verdicts">
            <VerdictCard
              layer="Layer 1 · Physics"
              status={!ph ? '—' : ph.verdict.veto ? 'VETO' : ph.verdict.score > 0 ? 'WARNING' : 'PASS'}
              cls={!ph ? 'muted' : ph.verdict.veto ? 'anomaly' : ph.verdict.score > 0 ? 'warning' : 'normal'}
              score={ph?.verdict.score}
              text={ph?.verdict.reason ?? 'Every physical law and bound checked is satisfied.'}
              active={tab === 'physics'} onClick={() => setTab('physics')} />
            <VerdictCard
              layer="Layer 3 · Multivariate"
              status={mv?.decision?.status ?? (mv ? 'LIMITED' : '—')}
              cls={!mv?.decision ? 'muted' : mv.decision.status === 'ANOMALY' ? 'anomaly' : mv.decision.status === 'SUSPICIOUS' ? 'warning' : 'normal'}
              score={mv?.layer_score}
              text={mv?.reason ?? (mv?.decision ? 'The joint T–RH–P state is consistent with this station, season and time of day.'
                : limitedText(mv))}
              active={tab === 'multivariate'} onClick={() => setTab('multivariate')} />
          </div>
          <div className="ll-fusion-note">
            In the full ATHER pipeline a physics <b>VETO</b> immediately makes the reading an anomaly; a Layer 3 <b>ANOMALY</b>
            (score ≥ 0.80) is an acute trigger on its own; <b>SUSPICIOUS</b> (0.60–0.74) raises a warning that needs other layers to agree.
          </div>

          <div className="ll-tabs" role="tablist">
            <button role="tab" aria-selected={tab === 'physics'} className={tab === 'physics' ? 'active' : ''} onClick={() => setTab('physics')}><Atom size={13} /> Physics · Layer 1</button>
            <button role="tab" aria-selected={tab === 'multivariate'} className={tab === 'multivariate' ? 'active' : ''} onClick={() => setTab('multivariate')}><Layers size={13} /> Multivariate · Layer 3</button>
            <button role="tab" aria-selected={tab === 'how'} className={tab === 'how' ? 'active' : ''} onClick={() => setTab('how')}><BookOpen size={13} /> How it works</button>
          </div>

          {tab === 'physics' && ph && (
            <div className="ll-tabpanel">
              <p className="ll-lead">
                Layer 1 asks one question: <b>could this reading exist in the real atmosphere at all?</b> Deterministic rules
                (bounds, psychrometrics, the wet-bulb limit, the hypsometric equation) have veto power. A physics-informed
                autoencoder then checks whether the three values are mutually consistent with the laws it was trained under.
              </p>
              <div className="section-card"><div className="card-section-title">RULE CHECKS — ALL EVALUATED, NONE HIDDEN</div><PhysicsChecklist trace={ph} /></div>
              <div className="section-card"><div className="card-section-title">PINN — PHYSICS-INFORMED RECONSTRUCTION</div><PinnPanel trace={ph} /></div>
            </div>
          )}

          {tab === 'multivariate' && mv && result && (
            <MultivariatePanel mv={mv} ctx={ctx} solarHour={solarHour}
              reading={{ t: result.input.temperature_c, rh: result.input.humidity_pct, p: result.input.pressure_hpa }} />
          )}

          {tab === 'how' && <HowItWorks alpha={result?.config.alpha ?? 0.01} window={result?.config.season_window_days ?? 30} />}
        </section>
      </div>
    </div>
  );
};

/** Plain-language status when Layer 3's learned models did not run. */
function limitedText(mv?: LabAnalysis['multivariate'] | null): string {
  if (!mv) return '';
  if (mv.method?.startsWith('2D')) {
    return 'Only two channels are valid (one failed its physical check), so the learned models, which need all three, were not used — a simple two-variable rule was applied instead.';
  }
  return mv.note ?? 'The learned models were not applied to this reading.';
}

const VerdictCard: React.FC<{ layer: string; status: string; cls: string; score?: number; text: string; active: boolean; onClick: () => void }> =
({ layer, status, cls, score, text, active, onClick }) => (
  <button className={`ll-verdict ll-verdict-${cls} ${active ? 'active' : ''}`} onClick={onClick}>
    <div className="ll-verdict-layer">{layer}</div>
    <div className="ll-verdict-status">
      {cls === 'anomaly' ? <XOctagon size={18} /> : cls === 'warning' ? <AlertTriangle size={18} /> : cls === 'normal' ? <CheckCircle2 size={18} /> : null}
      {status}
      {score !== undefined && <span className="ll-verdict-score">score {fmt(score, 2)}</span>}
    </div>
    <div className="ll-verdict-text">{text}</div>
  </button>
);

const MultivariatePanel: React.FC<{ mv: NonNullable<LabAnalysis['multivariate']>; ctx: LabContext | null; reading: { t: number; rh: number; p: number }; solarHour: number }> =
({ mv, ctx, reading, solarHour }) => {
  if (!mv.decision) {
    return (
      <div className="ll-tabpanel">
        <div className="section-card">
          <div className="card-section-title">NO LEARNED MODEL APPLIES</div>
          <p className="ll-lead">{limitedText(mv)}</p>
        </div>
      </div>
    );
  }
  const alpha = mv.alpha ?? 0.01;
  const td = mv.features?.dew_point_c ?? null;
  const rels = mv.relationships ?? {};
  const rows: [string, string, string][] = [
    ['both models flag', 'ANOMALY', 'HIGH'], ['exactly one flags', 'SUSPICIOUS', 'LOW'], ['neither flags', 'NORMAL', '—'],
  ];
  return (
    <div className="ll-tabpanel">
      <p className="ll-lead">
        Layer 3 asks: <b>is this combination of temperature, humidity and pressure normal for this station, this season and this
        time of day?</b> Each value can be perfectly plausible on its own while the <i>combination</i> is not.
      </p>

      <div className="ll-pipeline">
        {[
          ['Reading', `${fmt(reading.t)} °C · ${fmt(reading.rh, 0)} % · ${fmt(reading.p)} hPa`],
          ['Context', `${mv.reference_site} · ±${ctx?.season_window_days ?? 30} d · solar ${hhmm(solarHour)}`],
          ['Features', `${mv.feature_set === 'dynamic' ? 'with' : 'no'} rates of change · ${mv.model_features?.length ?? 0} inputs`],
          ['ECOD', mv.ecod?.anomaly ? 'flags' : 'no flag'],
          ['Isolation Forest', mv.isolation_forest?.anomaly ? 'flags' : 'no flag'],
          ['Decision', `${mv.decision.status} · ${mv.decision.confidence}`],
        ].map(([k, v], i) => (
          <div key={k} className={`ll-step ${(k === 'ECOD' && mv.ecod?.anomaly) || (k === 'Isolation Forest' && mv.isolation_forest?.anomaly) || (k === 'Decision' && mv.decision!.status !== 'NORMAL') ? 'is-hot' : ''}`}>
            <span className="ll-step-n">{i + 1}</span><span className="ll-step-k">{k}</span><span className="ll-step-v">{v}</span>
          </div>
        ))}
      </div>

      <div className="section-card">
        <div className="card-section-title">JOINT STATE — TEMPERATURE × HUMIDITY AT {mv.reference_site?.toUpperCase()}</div>
        {ctx?.scatter ? (
          <JointStateChart scatter={ctx.scatter} curve={ctx.relationship_curves?.t_rh} solarHour={solarHour}
                           reading={{ t: reading.t, rh: reading.rh }} site={mv.reference_site ?? ''} />
        ) : <div className="ll-note">Loading reference climatology…</div>}
        <div className="ll-note">
          Regional reference: <b>{mv.reference_site}</b>, {fmt(mv.reference_distance_km, 0)} km away · {ctx?.reference?.rows_in_season_window?.toLocaleString()} hourly
          observations within ±{ctx?.season_window_days} days of this date ({ctx?.reference?.years?.[0]}–{ctx?.reference?.years?.slice(-1)[0]}).
          A station switches to its own model after it has built enough trusted history.
        </div>
      </div>

      {ctx?.diurnal_profile && (
        <div className="section-card">
          <div className="card-section-title">CONTEXT — THE NORMAL DAILY CYCLE (5–95 % RANGE AND MEDIAN BY LOCAL SOLAR HOUR)</div>
          <div className="ll-small-multiples">
            <DiurnalChart profile={ctx.diurnal_profile} variable="t" title="Temperature" unit="°C" solarHour={solarHour} value={reading.t} />
            <DiurnalChart profile={ctx.diurnal_profile} variable="rh" title="Relative humidity" unit="%" solarHour={solarHour} value={reading.rh} decimals={0} />
            <DiurnalChart profile={ctx.diurnal_profile} variable="p" title="Pressure" unit="hPa" solarHour={solarHour} value={reading.p} />
            <DiurnalChart profile={ctx.diurnal_profile} variable="td" title="Dew point" unit="°C" solarHour={solarHour} value={td} />
          </div>
        </div>
      )}

      <div className="ll-two-col">
        <div className="section-card">
          <div className="card-section-title">LEARNED RELATIONSHIPS</div>
          {(['t_rh', 't_p'] as const).map((k) => {
            const r = rels[k];
            if (!r) return null;
            const off = Math.abs(r.residual_z) >= 2.5;
            return (
              <div key={k} className="ll-rel">
                <div className="ll-check-head">
                  <span className="ll-check-name">{k === 't_rh' ? 'Humidity given temperature' : 'Pressure given temperature'}</span>
                  <span className={`ll-status ll-status-${off ? 'warning' : 'normal'}`}>
                    {off ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />} {r.residual_z >= 0 ? '+' : ''}{fmt(r.residual_z, 2)} σ
                  </span>
                </div>
                <div className="ll-check-detail">
                  observed {fmt(r.observed, 1)} vs expected {fmt(r.expected, 1)} ± {fmt(r.residual_sd, 1)} {k === 't_rh' ? '%' : 'hPa'}
                  {' '}· relationship explains {fmt(r.r2 * 100, 0)} % of variance ({fmt(r.r2_gain_from_predictors * 100, 0)} points from temperature itself)
                </div>
              </div>
            );
          })}
          <div className="ll-note">Fitted per station and season by least squares, including the time of day. Relative humidity and pressure are not modelled against each other: the data shows no link between them once the daily cycle is removed.</div>
        </div>

        <div className="section-card">
          <div className="card-section-title">TWO INDEPENDENT MODELS, ONE EXPLICIT RULE</div>
          <ModelGauge name="ECOD" blurb="Sums how far into its own tail every input sits (empirical CDFs)."
                      p={mv.ecod?.p_value ?? null} score={mv.ecod?.score ?? null} alpha={alpha} minP={mv.min_attainable_p} />
          <ModelGauge name="Isolation Forest" blurb="Counts how few random cuts isolate this combination."
                      p={mv.isolation_forest?.p_value ?? null} score={mv.isolation_forest?.score ?? null} alpha={alpha} minP={mv.min_attainable_p} />
          <table className="ll-rule-table">
            <tbody>
              {rows.map(([when, status, conf]) => (
                <tr key={status} className={mv.decision!.status === status ? 'is-current' : ''}>
                  <td>{when}</td><td><b>{status}</b></td><td>{conf}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="ll-note">p-values are calibrated on {mv.calibration_samples?.toLocaleString()} held-out normal observations: α = {alpha} means each model is wrong on about 1 % of normal readings.</div>
        </div>
      </div>

      {mv.model_features && (
        <div className="section-card">
          <div className="card-section-title">EVIDENCE — WHERE EACH MODEL INPUT SITS IN THIS STATION'S HISTORY</div>
          <FeatureEvidence features={mv.model_features} alpha={alpha} />
        </div>
      )}

      {mv.clausius_clapeyron && (
        <div className="ll-error"><AlertTriangle size={14} /> Physical joint-state rule also fired: {mv.clausius_clapeyron.note}.</div>
      )}
    </div>
  );
};

const HowItWorks: React.FC<{ alpha: number; window: number }> = ({ alpha, window }) => (
  <div className="ll-tabpanel ll-how">
    <div className="section-card">
      <div className="card-section-title">LAYER 1 · PHYSICS INTELLIGENCE</div>
      <ol>
        <li><b>Hard bounds</b> — temperature, humidity and pressure must lie inside terrestrial physical limits.</li>
        <li><b>Psychrometrics</b> — the dew point can never exceed the air temperature (MetPy).</li>
        <li><b>Survivability</b> — a wet-bulb temperature above 35 °C cannot persist in nature.</li>
        <li><b>Hypsometric consistency</b> — pressure must agree with station altitude (standard atmosphere).</li>
        <li><b>PINN</b> — an autoencoder trained with a physics loss reconstructs a consistent (T, P, RH); large residuals add a soft, capped score. It never vetoes.</li>
      </ol>
      <p>A violated rule is a <b>veto</b>: deterministic, no statistics involved, so the reading is an anomaly whatever the other layers say.</p>
    </div>
    <div className="section-card">
      <div className="card-section-title">LAYER 3 · MULTIVARIATE INTELLIGENCE</div>
      <ol>
        <li><b>Inputs</b> — only temperature, relative humidity, sea-level pressure and the verified observation time.</li>
        <li><b>Model choice</b> — the station's own model once it has enough trusted history; otherwise the nearest regional reference within 75 km (10 years of hourly Open-Meteo data), trained on ±{window} days of the same calendar date.</li>
        <li><b>Features</b> — each value and its dew point as a departure from the normal for that hour; learned residuals of humidity and pressure given temperature; rates of change when a recent previous reading exists.</li>
        <li><b>Two detectors</b> — ECOD (per-feature tails, summed) and Isolation Forest (joint isolation). Each gives a p-value against held-out normal data.</li>
        <li><b>Decision</b> — both p ≤ {alpha} → ANOMALY; one → SUSPICIOUS; none → NORMAL.</li>
        <li><b>Safe learning</b> — only readings judged normal (and not flagged by Layers 1–2) are added to the station's history; anomalies never train the model meant to catch them.</li>
      </ol>
    </div>
    <div className="section-card">
      <div className="card-section-title">WHAT THE VALIDATION SAYS (HELD-OUT 2023–24, 24 INDIAN SITES)</div>
      <p>On normal data about 1.1 % of readings reach ANOMALY and 1.9 % are flagged at all. On injected relationship-breaking faults, 51 % of rows and 77 % of events are flagged,
         well ahead of per-channel checks (F1 0.26). Pressure-only faults are mostly out of reach, because pressure is only weakly tied to temperature and humidity.</p>
    </div>
  </div>
);
