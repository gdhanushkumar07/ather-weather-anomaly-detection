/** Types for the Layer Lab API (backend/app/layers/lab_service.py). */

export type CheckStatus = 'pass' | 'veto' | 'warn' | 'skipped';

export interface PhysicsCheck {
  id: string;
  name: string;
  principle: string;
  status: CheckStatus;
  value?: number;
  lower?: number;
  upper?: number;
  limit?: number;
  expected?: number;
  deviation_pct?: number;
  tolerance_pct?: number;
  elevation_m?: number;
  unit?: string;
  note?: string;
}

export interface PinnChannel {
  channel: 'temperature_c' | 'pressure_hpa' | 'humidity_pct';
  observed: number;
  expected: number;
  residual: number;
  tolerance: number;
  z: number;
}

export interface PhysicsTrace {
  verdict: { score: number; veto: boolean; reason: string | null };
  checks: PhysicsCheck[];
  pinn: {
    available: boolean;
    score?: number;
    reason?: string | null;
    channels?: PinnChannel[];
    flag_starts_at_z?: number;
    saturates_at_z?: number;
    max_score?: number;
  };
  elevation_m: number;
}

export interface ModelEvidence { enabled: boolean; score: number | null; p_value: number | null; anomaly: boolean | null }

export interface Relationship {
  target: string;
  used_by_models: boolean;
  observed: number;
  expected: number;
  residual_sd: number;
  residual_z: number;
  r2: number;
  r2_gain_from_predictors: number;
}

export interface ModelFeature {
  feature: string;
  base_feature: string;
  value: number;
  percentile: number;
  tail_probability: number;
  observed: number | null;
  expected_for_hour: number | null;
  kind: 'contextual' | 'relationship' | 'rate_of_change';
}

export interface MultivariateTrace {
  layer_score: number;
  reason: string | null;
  status: string;
  method?: string;
  valid_channel_count?: number;
  clausius_clapeyron?: { temperature_c: number; humidity_pct: number; score: number; note: string } | null;
  model_source?: 'station_history' | 'regional_reference' | 'none';
  reference_site?: string;
  reference_distance_km?: number;
  reference_month?: number;
  feature_set?: 'static' | 'dynamic';
  training_samples?: number;
  calibration_samples?: number;
  min_attainable_p?: number;
  alpha?: number;
  ecod?: ModelEvidence;
  isolation_forest?: ModelEvidence;
  decision?: { status: 'NORMAL' | 'SUSPICIOUS' | 'ANOMALY'; confidence: string; layer3_anomaly: boolean; layer_score: number };
  relationships?: Partial<Record<'t_rh' | 't_p', Relationship>>;
  features?: Record<string, number | null>;
  model_features?: ModelFeature[];
  tail_floor?: number;
  status_ml?: string;
  note?: string;
}

export interface LabAnalysis {
  input: { timestamp: string; latitude: number; longitude: number; elevation_m: number; solar_hour: number;
           temperature_c: number; pressure_hpa: number; humidity_pct: number; dew_point_c?: number | null };
  physics: PhysicsTrace;
  multivariate: MultivariateTrace;
  config: { alpha: number; season_window_days: number };
}

export interface ScatterPoint { t: number; rh: number; p: number; h: number }
export interface ProfileRow {
  hour: number;
  t_p05: number; t_p50: number; t_p95: number;
  rh_p05: number; rh_p50: number; rh_p95: number;
  p_p05: number; p_p50: number; p_p95: number;
  td_p05: number; td_p50: number; td_p95: number;
}
export interface RelationshipCurve { t: number[]; expected: number[]; sd: number }

export interface LabPreset {
  id: string;
  label: string;
  expect: 'NORMAL' | 'MULTIVARIATE' | 'EVIDENCE' | 'PHYSICS';
  description: string;
  reading: { temperature_c: number; humidity_pct: number; pressure_hpa: number; dew_point_c?: number };
}

export interface LabContext {
  timestamp: string;
  solar_hour: number;
  season_window_days: number;
  alpha: number;
  reference: null | { site: string; distance_km: number; latitude: number; longitude: number; rows_in_season_window: number; years: number[] };
  note?: string;
  scatter?: ScatterPoint[];
  diurnal_profile?: ProfileRow[];
  relationship_curves?: Partial<Record<'t_rh' | 't_p', RelationshipCurve>>;
  presets?: LabPreset[];
}

export interface LabReadingInput {
  latitude: number;
  longitude: number;
  elevation_m?: number;
  timestamp: string;
  temperature_c: number;
  pressure_hpa: number;
  humidity_pct: number;
  dew_point_c?: number | null;
  previous?: { temperature_c: number; pressure_hpa: number; humidity_pct: number; minutes_before: number } | null;
}
