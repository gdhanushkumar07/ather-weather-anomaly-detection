export interface PredefinedScenario {
  id: string;
  name: string;
  description: string;
  step_count: number;
  expected_bucket: string;
  expected_root_cause_hint: string;
  baseline: {
    temperature: number;
    pressure: number;
    humidity: number;
  };
  injected: {
    temperature: number | null;
    pressure: number | null;
    humidity: number | null;
  };
  time_series_preview?: Array<{
    step: number;
    temperature: number | null;
    pressure: number | null;
    humidity: number | null;
  }>;
}

export const PREDEFINED_SCENARIOS: PredefinedScenario[] = [
  {
    id: "TEMPERATURE_SPIKE",
    name: "Temperature Spike",
    description: "A sudden, physically implausible jump in a single reading (+11.5°C) after several stable baseline readings.",
    step_count: 4,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "SENSOR_SPIKE / SINGLE_CHANNEL_FAULT",
    baseline: { temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 43.5, pressure: 1013.0, humidity: 55.0 },
    time_series_preview: [
      { step: 1, temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
      { step: 2, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
      { step: 3, temperature: 31.9, pressure: 1013.0, humidity: 55.0 },
      { step: 4, temperature: 43.5, pressure: 1013.0, humidity: 55.0 },
    ]
  },
  {
    id: "FROZEN_TEMPERATURE_SENSOR",
    name: "Frozen Temperature Sensor",
    description: "The same exact temperature value repeated across 14 consecutive observations (stuck ADC / sensor lockup).",
    step_count: 14,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "FROZEN_SENSOR",
    baseline: { temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
    time_series_preview: [
      { step: 1, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
      { step: 2, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
      { step: 3, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
      { step: 4, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
      { step: 5, temperature: 32.1, pressure: 1013.0, humidity: 55.0 },
    ]
  },
  {
    id: "TEMPERATURE_SENSOR_DRIFT",
    name: "Temperature Sensor Drift",
    description: "A slow, monotonic upward creep in temperature (+0.4°C every ~10 min across 20 readings) consistent with calibration drift.",
    step_count: 20,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "CALIBRATION_DRIFT",
    baseline: { temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 39.6, pressure: 1013.0, humidity: 55.0 },
    time_series_preview: [
      { step: 1, temperature: 32.0, pressure: 1012.9, humidity: 54.9 },
      { step: 5, temperature: 33.6, pressure: 1013.1, humidity: 55.1 },
      { step: 10, temperature: 35.6, pressure: 1012.9, humidity: 55.0 },
      { step: 15, temperature: 37.6, pressure: 1013.1, humidity: 54.9 },
      { step: 20, temperature: 39.6, pressure: 1013.0, humidity: 55.0 },
    ]
  },
  {
    id: "IMPOSSIBLE_HUMIDITY",
    name: "Impossible Humidity",
    description: "Relative humidity reported at 135% — a physically impossible value that fails data-quality/physics validation.",
    step_count: 1,
    expected_bucket: "DATA_QUALITY_VIOLATION",
    expected_root_cause_hint: "Physics veto (impossible humidity)",
    baseline: { temperature: 30.0, pressure: 1012.0, humidity: 55.0 },
    injected: { temperature: 30.0, pressure: 1012.0, humidity: 135.0 },
    time_series_preview: [
      { step: 1, temperature: 30.0, pressure: 1012.0, humidity: 135.0 }
    ]
  },
  {
    id: "PRESSURE_SPIKE",
    name: "Pressure Spike",
    description: "A transient barometric pressure spike to 1075 hPa before recovering to normal 1013 hPa.",
    step_count: 6,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "SENSOR_SPIKE (transient physics veto visible mid-sequence)",
    baseline: { temperature: 28.0, pressure: 1012.0, humidity: 60.0 },
    injected: { temperature: 28.0, pressure: 1075.0, humidity: 60.0 },
    time_series_preview: [
      { step: 1, temperature: 28.0, pressure: 1012.0, humidity: 60.0 },
      { step: 2, temperature: 28.0, pressure: 1012.0, humidity: 60.0 },
      { step: 3, temperature: 28.0, pressure: 1013.0, humidity: 60.0 },
      { step: 4, temperature: 28.0, pressure: 1014.0, humidity: 60.0 },
      { step: 5, temperature: 28.0, pressure: 1075.0, humidity: 60.0 },
      { step: 6, temperature: 28.0, pressure: 1013.0, humidity: 60.0 },
    ]
  },
  {
    id: "MISSING_TELEMETRY",
    name: "Missing Telemetry",
    description: "Only one channel is reported (Pressure=null, Humidity=null) — ATHER reports insufficient data, never fabricates a fault.",
    step_count: 1,
    expected_bucket: "NORMAL",
    expected_root_cause_hint: "NORMAL overall; temporal/multivariate/spatial/sensor_health report INSUFFICIENT_DATA",
    baseline: { temperature: 29.0, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 29.0, pressure: null, humidity: null },
    time_series_preview: [
      { step: 1, temperature: 29.0, pressure: null, humidity: null }
    ]
  },
  {
    id: "MULTIVARIATE_INCONSISTENCY",
    name: "Multivariate Inconsistency",
    description: "High heat (33°C) combined with saturated humidity (96%) at sea level pressure — trips joint multivariate boundary.",
    step_count: 3,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "Multivariate (Clausius-Clapeyron) inconsistency",
    baseline: { temperature: 30.0, pressure: 1013.0, humidity: 60.0 },
    injected: { temperature: 33.0, pressure: 1013.0, humidity: 96.0 },
    time_series_preview: [
      { step: 1, temperature: 30.0, pressure: 1013.0, humidity: 60.0 },
      { step: 2, temperature: 31.5, pressure: 1012.0, humidity: 70.0 },
      { step: 3, temperature: 33.0, pressure: 1013.0, humidity: 96.0 },
    ]
  },
  {
    id: "SPATIAL_OUTLIER",
    name: "Spatial Outlier",
    description: "Target station reports 45°C while all 4 nearby stations report 31–34°C — spatial divergence without regional support.",
    step_count: 1,
    expected_bucket: "LIKELY_SENSOR_ANOMALY",
    expected_root_cause_hint: "SINGLE_CHANNEL_FAULT (spatial outlier)",
    baseline: { temperature: 32.0, pressure: 1013.0, humidity: 46.0 },
    injected: { temperature: 45.0, pressure: 1013.0, humidity: 45.0 },
    time_series_preview: [
      { step: 1, temperature: 45.0, pressure: 1013.0, humidity: 45.0 }
    ]
  },
  {
    id: "REGIONAL_WEATHER_EVENT",
    name: "Regional Weather Event",
    description: "Target station jumps +6°C, but all surrounding neighbor stations experience the same jump simultaneously.",
    step_count: 2,
    expected_bucket: "POSSIBLE_WEATHER_EVENT",
    expected_root_cause_hint: "GENUINE_EXTREME_WEATHER / POSSIBLE_WEATHER_CHANGE",
    baseline: { temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 38.0, pressure: 1011.0, humidity: 48.0 },
    time_series_preview: [
      { step: 1, temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
      { step: 2, temperature: 38.0, pressure: 1011.0, humidity: 48.0 },
    ]
  },
  {
    id: "COMBINED_SENSOR_FAILURE",
    name: "Combined Sensor Failure",
    description: "Temperature spike (40°C), extreme humidity (90%), temporal discontinuity with zero regional support — trips physics wet-bulb veto.",
    step_count: 3,
    expected_bucket: "DATA_QUALITY_VIOLATION",
    expected_root_cause_hint: "Physics veto (wet-bulb) + temporal + multivariate + spatial all agreeing",
    baseline: { temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
    injected: { temperature: 40.0, pressure: 1013.0, humidity: 90.0 },
    time_series_preview: [
      { step: 1, temperature: 32.0, pressure: 1013.0, humidity: 55.0 },
      { step: 2, temperature: 32.1, pressure: 1013.0, humidity: 54.0 },
      { step: 3, temperature: 40.0, pressure: 1013.0, humidity: 90.0 },
    ]
  }
];
