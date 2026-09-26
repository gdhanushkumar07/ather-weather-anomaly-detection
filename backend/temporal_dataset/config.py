"""
Configuration for the Stage 1 synthetic temporal dataset generator.

All generation parameters live here so the generator is configurable and
reproducible without touching generation logic. Physical plausibility
bounds are deliberately NOT duplicated here — they are read from the
existing `config.CONFIG.physics` at generation time (see station_selection.py
and sequence_generator.py) so this generator can never silently disagree
with the physics layer the rest of ATHER already uses.
"""
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Source of per-station baselines (existing ATHER station snapshot).
DEFAULT_SOURCE_STATIONS_PATH = REPO_ROOT / "data" / "stations.json"

# Output location for generated artifacts (new, generator-owned directory).
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "data" / "temporal"


@dataclass
class TemporalGeneratorConfig:
    # ── Locked design decisions (Stage 1 spec) ─────────────────────────
    sampling_interval_minutes: int = 10
    sequence_length_steps: int = 144       # 24h reference window for the FUTURE LSTM task (not sliced here)
    history_days: int = 7                  # 7 days x 24h x 6/h = 1008 observations per station

    # ── Station selection ───────────────────────────────────────────────
    num_stations: int = 500                # configurable target station count (e.g. 500 / 1000 / 1655)
    exclude_null_island: bool = True       # exclude exact (0.0, 0.0) — see station_selection.py docstring

    # ── Reproducibility ──────────────────────────────────────────────────
    seed: int = 42

    # ── Train / validation / test split (station-level, not row-level) ──
    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15

    # ── Temperature generation ───────────────────────────────────────────
    diurnal_amplitude_c: float = 5.0           # half-range of the diurnal sinusoid, deg C
    diurnal_peak_local_hour: float = 15.0      # afternoon peak (~3pm local solar time), not solar noon
    scale_amplitude_by_latitude: bool = True   # mild realism: bigger diurnal swing away from the equator
    temp_slow_rho: float = 0.995               # AR(1) coefficient, slow component (near-random-walk, mean-reverting)
    temp_slow_sigma: float = 0.05              # innovation std-dev per 10-min step, deg C
    temp_fast_rho: float = 0.7                 # AR(1) coefficient, fast/short-term component
    temp_fast_sigma: float = 0.3               # innovation std-dev per 10-min step, deg C

    # ── Humidity generation (coupled to temperature) ─────────────────────
    # RH(t) = RH_base - k_RH * (T(t) - T_base) + noise, clipped to [0, 100].
    # k_RH is a starting value chosen to produce a few %RH per °C of
    # temperature deviation (a well-known qualitative diurnal relationship:
    # RH falls as air warms during the day). It is validated, not assumed —
    # see validation.temperature_humidity_relationship().
    humidity_temp_coupling_pct_per_c: float = 2.5
    humidity_fast_rho: float = 0.7
    humidity_fast_sigma: float = 1.5           # innovation std-dev per 10-min step, %RH

    # ── Pressure generation (slow, largely non-diurnal) ──────────────────
    pressure_slow_rho: float = 0.995
    pressure_slow_sigma: float = 0.03          # hPa per 10-min step
    pressure_fast_rho: float = 0.5
    pressure_fast_sigma: float = 0.08          # hPa per 10-min step

    # ── I/O ────────────────────────────────────────────────────────────
    source_stations_path: Path = field(default_factory=lambda: DEFAULT_SOURCE_STATIONS_PATH)
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    normal_dataset_filename: str = "synthetic_temporal_normal.csv"
    metadata_filename: str = "synthetic_temporal_metadata.json"
    validation_filename: str = "synthetic_temporal_validation.json"

    @property
    def total_steps_per_station(self) -> int:
        steps_per_day = (24 * 60) // self.sampling_interval_minutes
        return steps_per_day * self.history_days

    def __post_init__(self):
        ratio_sum = round(self.train_ratio + self.val_ratio + self.test_ratio, 6)
        if ratio_sum != 1.0:
            raise ValueError(f"train/val/test ratios must sum to 1.0, got {ratio_sum}")
        if self.num_stations <= 0:
            raise ValueError("num_stations must be positive")
        if self.sampling_interval_minutes <= 0 or (24 * 60) % self.sampling_interval_minutes != 0:
            raise ValueError("sampling_interval_minutes must evenly divide 24h")
