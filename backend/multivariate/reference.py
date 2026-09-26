"""
Regional historical reference models — Layer 3's cold start for live stations.

WHY: ATHER evaluates a live station only a handful of times (startup,
on-demand fetches, pushed telemetry). A station therefore needs weeks before
its OWN trusted history reaches min_train_samples, and until then a purely
online Layer 3 would have nothing but a generic prior. Every one of ATHER's
296 WeatherUnion AWS locations lies within ~45 km of one of the 24 reference
sites, so each can be scored from its first reading against a model of the
nearest site's historical joint behaviour for the same season.

WHAT: for (site, calendar month, feature set) a DetectorPair is trained on the
site's Open-Meteo hourly history within +-season_window_days of the
15th of that month (all years), split into fit and conformal-calibration
rows by training.split_fit_calibration (day-blocked interleave). Models are trained
lazily on first use and kept in a small LRU cache.

The historical CSV is converted once into per-site .npz files under
reference_cache_dir (a derived, gitignored cache), so live startup never
re-parses the 126 MB CSV.

LIMITATION: the live feed is Open-Meteo's *forecast* model output at the
station's own coordinates; the reference is ERA5-based *reanalysis* at the
city centre. Systematic differences between the two (grid, model, siting)
remain; the live smoke test in evaluation reports how often live readings
are flagged. A station's own models replace the reference once it has
min_train_samples trusted observations.
"""
import logging
import math
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from multivariate import schema as S
from multivariate.features import add_features
from multivariate.models import DetectorPair
from multivariate.training import fit_pair, month_center_doy, seasonal_mask, split_fit_calibration

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


class ReferenceLibrary:
    def __init__(self, cfg):
        self.cfg = cfg
        self.csv_path = (BACKEND_DIR / cfg.reference_data_path).resolve()
        self.cache_dir = (BACKEND_DIR / cfg.reference_cache_dir).resolve()
        self._sites: Optional[Dict[str, Tuple[float, float]]] = None
        self._frames: Dict[str, pd.DataFrame] = {}
        self._models: "OrderedDict[tuple, Optional[DetectorPair]]" = OrderedDict()
        self.available = True

    @classmethod
    def from_frame(cls, cfg, df: pd.DataFrame) -> "ReferenceLibrary":
        """Reference library over an in-memory standard-schema frame (one or
        more sites) instead of the on-disk cache — same model-building path."""
        lib = cls(cfg)
        lib._sites = {}
        for site, g in df.groupby(S.STATION_ID):
            lib._sites[site] = (float(g[S.LATITUDE].iloc[0]), float(g[S.LONGITUDE].iloc[0]))
            lib._frames[site] = add_features(g, cfg.max_delta_gap_hours)
        return lib

    # ── site catalogue ──────────────────────────────────────────────────
    def _ensure_cache(self) -> None:
        if self._sites is not None:
            return
        index = self.cache_dir / "sites.csv"
        if not index.exists():
            if not self.csv_path.exists():
                logger.warning("Layer 3 reference data not found at %s — regional reference disabled "
                               "(python -m multivariate.download open-meteo)", self.csv_path)
                self._sites, self.available = {}, False
                return
            self._build_cache()
        sites = pd.read_csv(index)
        self._sites = {r.site: (float(r.latitude), float(r.longitude)) for r in sites.itertuples()}

    def _build_cache(self) -> None:
        from multivariate.datasets import load_open_meteo
        logger.info("Building Layer 3 reference cache from %s", self.csv_path)
        df, _ = load_open_meteo(self.csv_path)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for site, g in df.groupby(S.STATION_ID):
            np.savez_compressed(
                self.cache_dir / f"{_slug(site)}.npz",
                t_s=pd.DatetimeIndex(g[S.TIMESTAMP]).tz_convert(None).as_unit("s").asi8,
                temperature_c=g[S.TEMPERATURE].to_numpy(np.float32),
                pressure_hpa=g[S.PRESSURE].to_numpy(np.float32),
                humidity_pct=g[S.HUMIDITY].to_numpy(np.float32),
            )
            rows.append({"site": site, "latitude": g[S.LATITUDE].iloc[0], "longitude": g[S.LONGITUDE].iloc[0]})
        pd.DataFrame(rows).to_csv(self.cache_dir / "sites.csv", index=False)

    def nearest_site(self, lat: float, lon: float) -> Optional[Tuple[str, float]]:
        self._ensure_cache()
        if not self._sites or (lat == 0.0 and lon == 0.0):
            return None
        best = min(((s, haversine_km(lat, lon, la, lo)) for s, (la, lo) in self._sites.items()), key=lambda x: x[1])
        return best if best[1] <= self.cfg.reference_max_distance_km else None

    def _frame(self, site: str) -> pd.DataFrame:
        if site not in self._frames:
            z = np.load(self.cache_dir / f"{_slug(site)}.npz")
            la, lo = self._sites[site]
            df = pd.DataFrame({
                S.STATION_ID: site,
                S.TIMESTAMP: pd.to_datetime(z["t_s"], unit="s", utc=True),
                S.TEMPERATURE: z["temperature_c"].astype(float),
                S.PRESSURE: z["pressure_hpa"].astype(float),
                S.HUMIDITY: z["humidity_pct"].astype(float),
                S.LATITUDE: la, S.LONGITUDE: lo,
            })
            self._frames[site] = add_features(df, self.cfg.max_delta_gap_hours)
        return self._frames[site]

    def season_frame(self, site: str, when_utc) -> pd.DataFrame:
        """The exact seasonal-window rows the (site, month) models are trained on."""
        month = pd.Timestamp(when_utc).month
        frame = self._frame(site)
        return frame[seasonal_mask(frame[S.TIMESTAMP], month_center_doy(month), self.cfg.season_window_days)]

    # ── models ──────────────────────────────────────────────────────────
    def pair_for(self, site: str, when_utc, kind: str) -> Optional[DetectorPair]:
        month = pd.Timestamp(when_utc).month
        key = (site, month, kind)
        if key in self._models:
            self._models.move_to_end(key)
            return self._models[key]
        frame = self._frame(site)
        season = frame[seasonal_mask(frame[S.TIMESTAMP], month_center_doy(month), self.cfg.season_window_days)]
        pair = fit_pair(*split_fit_calibration(season, self.cfg.calibration_fraction), kind, self.cfg)
        self._models[key] = pair
        while len(self._models) > self.cfg.reference_max_cached_models:
            self._models.popitem(last=False)
        return pair


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)
