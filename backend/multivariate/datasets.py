"""
Dataset adapters: raw file -> standard schema (multivariate/schema.py).

This is the ONLY module that knows dataset-specific column names, units and
timezones. Each loader returns (standardized_frame, report_dict).

  open_meteo   Open-Meteo Historical Weather API export (ERA5-based
               reanalysis), 24 Indian cities, hourly 2015-2024.
               PRIMARY: same provider and same variables (temperature_2m,
               relative_humidity_2m, pressure_msl) as ATHER's live feed, so it
               is what the live regional reference models are trained on.
  isd_lite     NOAA NCEI Integrated Surface Database "ISD-Lite": real in-situ
               synoptic/airport station observations. RH is derived from the
               observed air temperature and dew point.
  synthetic    ATHER's Stage 1 synthetic temporal dataset (temporal_dataset/).
               Controlled/secondary only — its T-RH coupling is a formula.
  csv          any CSV with user-supplied column names.
"""
import gzip
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from multivariate import schema as S
from multivariate.features import relative_humidity_from_dew_point
from multivariate.preprocessing import standardize

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

OPEN_METEO_DEFAULT_PATH = REPO_ROOT / "data" / "historical" / "open_meteo_india_hourly.csv"
OPEN_METEO_TIMEZONE = "Asia/Kolkata"   # the export was requested with timezone=Asia/Kolkata
ISD_DEFAULT_DIR = REPO_ROOT / "data" / "raw" / "isd_lite"
SYNTHETIC_DEFAULT_DIR = BACKEND_DIR / "data" / "temporal"


def load_open_meteo(path: Path = OPEN_METEO_DEFAULT_PATH, stations=None) -> Tuple[pd.DataFrame, Dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create it with: python -m multivariate.download open-meteo")
    usecols = ["station", "latitude", "longitude", "timestamp", "temperature_c", "humidity_pct", "pressure_hpa"]
    raw = pd.read_csv(path, usecols=usecols)
    if stations:
        raw = raw[raw["station"].isin(stations)]
    df = raw.rename(columns={"station": S.STATION_ID})
    # Naive local wall-clock times -> tz-aware. IST has no DST, so this is unambiguous.
    df[S.TIMESTAMP] = pd.to_datetime(df[S.TIMESTAMP]).dt.tz_localize(OPEN_METEO_TIMEZONE)
    out, rep = standardize(df)
    rep.update({"dataset": "open_meteo_historical", "source_file": str(path),
                "pressure": "pressure_msl (mean-sea-level)", "native_timezone": OPEN_METEO_TIMEZONE})
    return out, rep


def load_isd_lite(directory: Path = ISD_DEFAULT_DIR) -> Tuple[pd.DataFrame, Dict]:
    """
    ISD-Lite fixed-format fields (space separated, -9999 = missing):
      year month day hour(UTC) air_temp*10 dew_point*10 slp*10 wind_dir wind_speed*10 sky precip1 precip6
    """
    directory = Path(directory)
    manifest_path = directory / "stations.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path} not found. Create it with: python -m multivariate.download isd")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = []
    for st in manifest["stations"]:
        for f in sorted(directory.glob(f"{st['usaf']}-{st['wban']}-*.gz")):
            with gzip.open(f, "rt") as fh:
                arr = np.loadtxt(fh, dtype=np.int64, ndmin=2)
            if arr.size == 0:
                continue
            t, td, slp = arr[:, 4].astype(float), arr[:, 5].astype(float), arr[:, 6].astype(float)
            for a in (t, td, slp):
                a[a == -9999] = np.nan
            t, td, slp = t / 10.0, td / 10.0, slp / 10.0
            ts = pd.to_datetime(dict(year=arr[:, 0], month=arr[:, 1], day=arr[:, 2], hour=arr[:, 3]), utc=True)
            frames.append(pd.DataFrame({
                S.STATION_ID: st["name"],
                S.TIMESTAMP: ts,
                S.TEMPERATURE: t,
                S.PRESSURE: slp,
                S.HUMIDITY: relative_humidity_from_dew_point(t, td),
                "dew_point_observed_c": td,
                S.LATITUDE: st["lat"],
                S.LONGITUDE: st["lon"],
            }))
    if not frames:
        raise FileNotFoundError(f"No ISD-Lite files in {directory}")
    df = pd.concat(frames, ignore_index=True)
    # Td > T by more than rounding -> physically inconsistent record (Layer 1 territory), RH > 100.
    df.loc[df[S.HUMIDITY] > 100.5, S.HUMIDITY] = np.nan
    df[S.HUMIDITY] = df[S.HUMIDITY].clip(upper=100.0)
    out, rep = standardize(df)
    rep.update({"dataset": "noaa_isd_lite", "source_dir": str(directory),
                "pressure": "sea-level pressure (observed)",
                "humidity": "derived from observed T and dew point (Magnus, Alduchov & Eskridge 1996)",
                "stations_manifest": manifest["stations"]})
    return out, rep


def load_synthetic_temporal(directory: Path = SYNTHETIC_DEFAULT_DIR) -> Tuple[pd.DataFrame, Dict]:
    directory = Path(directory)
    csv_path = directory / "synthetic_temporal_normal.csv"
    meta_path = directory / "synthetic_temporal_metadata.json"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Create it with: python -m temporal_dataset.generate_dataset")
    raw = pd.read_csv(csv_path)
    df = raw.rename(columns={"relative_humidity_pct": S.HUMIDITY})
    df[S.TIMESTAMP] = pd.to_datetime(df[S.TIMESTAMP], utc=True)
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        loc = pd.DataFrame(meta["stations"])[["station_id", "latitude", "longitude"]]
        df = df.merge(loc, on="station_id", how="left")
    out, rep = standardize(df)
    rep.update({"dataset": "ather_synthetic_temporal", "source_file": str(csv_path),
                "note": "Synthetic: RH is generated as a linear function of T plus AR(1) noise; "
                        "pressure is generated independently of T and RH."})
    return out, rep


def load_csv(path: Path, station_col: str, time_col: str, temp_col: str, pressure_col: str,
             humidity_col: str, timezone: str = "UTC", lat_col: Optional[str] = None,
             lon_col: Optional[str] = None) -> Tuple[pd.DataFrame, Dict]:
    raw = pd.read_csv(path)
    mapping = {station_col: S.STATION_ID, time_col: S.TIMESTAMP, temp_col: S.TEMPERATURE,
               pressure_col: S.PRESSURE, humidity_col: S.HUMIDITY}
    if lat_col:
        mapping[lat_col] = S.LATITUDE
    if lon_col:
        mapping[lon_col] = S.LONGITUDE
    df = raw.rename(columns=mapping)
    ts = pd.to_datetime(df[S.TIMESTAMP])
    df[S.TIMESTAMP] = ts.dt.tz_localize(timezone) if ts.dt.tz is None else ts
    out, rep = standardize(df)
    rep.update({"dataset": "csv", "source_file": str(path), "column_mapping": mapping, "timezone": timezone})
    return out, rep


LOADERS = {
    "open_meteo": load_open_meteo,
    "isd": load_isd_lite,
    "synthetic_temporal": load_synthetic_temporal,
}
