"""
Reproducible download of Layer 3's real datasets.

    python -m multivariate.download open-meteo   # -> data/historical/open_meteo_india_hourly.csv
    python -m multivariate.download isd          # -> data/raw/isd_lite/*.gz + stations.json

Both outputs are large, reproducible raw data and are gitignored.

OPEN-METEO — Historical Weather API (https://open-meteo.com/en/docs/historical-weather-api),
  endpoint https://archive-api.open-meteo.com/v1/archive. Hourly
  temperature_2m, relative_humidity_2m, pressure_msl, surface_pressure,
  requested with timezone=Asia/Kolkata. Data licence: CC BY 4.0 (attribute
  Open-Meteo; underlying reanalysis: Copernicus ERA5 / ECMWF).
  This reproduces the existing ATHER export exactly (verified: Delhi
  2015-01-01 00:00-03:00 = 12.2, 12.9, 13.2, 13.1 C in both).

NOAA ISD-LITE — https://www.ncei.noaa.gov/pub/data/noaa/isd-lite/{year}/{USAF}-{WBAN}-{year}.gz
  Station catalogue: https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv
  US-government data; NOAA asks that WMO-resolution-40 restrictions on
  redistribution of some non-US data for commercial use be respected.
  For each city the first candidate station with enough complete
  (T, dew point, sea-level pressure) records is used; candidates were taken
  from isd-history.csv as the nearest stations active through 2025.
"""
import argparse
import gzip
import io
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from multivariate.datasets import ISD_DEFAULT_DIR, OPEN_METEO_DEFAULT_PATH, OPEN_METEO_TIMEZONE

USER_AGENT = "ATHER-Weather-Intelligence/1.0 (academic-monitoring)"

# The 24 reference sites of the existing export, with the exact coordinates
# stored in it (name, lat, lon).
OPEN_METEO_SITES = [
    ("Ahmedabad", 23.02, 72.57), ("Bengaluru", 12.97, 77.59), ("Bhopal", 23.26, 77.41),
    ("Bhubaneswar", 20.30, 85.82), ("Chandigarh", 30.73, 76.78), ("Chennai", 13.08, 80.27),
    ("Delhi", 28.61, 77.21), ("Guwahati", 26.14, 91.74), ("Hyderabad", 17.38, 78.49),
    ("Jaipur", 26.91, 75.79), ("Jaisalmer", 26.92, 70.91), ("Kochi", 9.93, 76.27),
    ("Kolkata", 22.57, 88.36), ("Leh", 34.15, 77.58), ("Lucknow", 26.85, 80.95),
    ("Mumbai", 19.08, 72.88), ("Nagpur", 21.15, 79.09), ("Patna", 25.59, 85.14),
    ("Port Blair", 11.62, 92.73), ("Pune", 18.52, 73.86), ("Shimla", 31.10, 77.17),
    ("Srinagar", 34.08, 74.80), ("Thiruvananthapuram", 8.52, 76.94), ("Visakhapatnam", 17.69, 83.22),
]

ISD_CANDIDATES = {
    "Delhi": ["421820-99999", "421810-99999"],
    "Mumbai": ["430030-99999", "430570-99999"],
    "Chennai": ["432780-99999", "432790-99999"],
    "Kolkata": ["428070-99999", "428090-99999"],
    "Bengaluru": ["433025-99999", "427056-99999", "432950-99999"],
    "Hyderabad": ["431280-99999", "431285-99999"],
    "Pune": ["430630-99999", "430670-99999"],
}


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_open_meteo(out_path: Path = OPEN_METEO_DEFAULT_PATH, start: str = "2015-01-01",
                        end: str = "2024-12-31") -> Path:
    frames = []
    for name, lat, lon in OPEN_METEO_SITES:
        url = ("https://archive-api.open-meteo.com/v1/archive?"
               f"latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
               "&hourly=temperature_2m,relative_humidity_2m,pressure_msl,surface_pressure"
               f"&timezone={OPEN_METEO_TIMEZONE.replace('/', '%2F')}")
        h = json.loads(_get(url))["hourly"]
        frames.append(pd.DataFrame({
            "station": name, "latitude": round(lat, 2), "longitude": round(lon, 2), "timestamp": h["time"],
            "temperature_c": h["temperature_2m"], "humidity_pct": h["relative_humidity_2m"],
            "pressure_hpa": h["pressure_msl"], "surface_pressure_hpa": h["surface_pressure"],
        }))
        print(f"  {name}: {len(h['time'])} hours")
        time.sleep(1.0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_csv(out_path, index=False)
    return out_path


def _isd_complete_rows(raw_gz: bytes) -> int:
    with gzip.open(io.BytesIO(raw_gz), "rt") as fh:
        a = np.loadtxt(fh, dtype=np.int64, ndmin=2)
    return int(((a[:, 4] != -9999) & (a[:, 5] != -9999) & (a[:, 6] != -9999)).sum()) if a.size else 0


def download_isd(out_dir: Path = ISD_DEFAULT_DIR, years=range(2019, 2025), min_complete_per_year: int = 1500) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    hist = pd.read_csv(io.BytesIO(_get("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv")), dtype=str)
    hist["key"] = hist["USAF"] + "-" + hist["WBAN"]
    chosen = []
    for city, candidates in ISD_CANDIDATES.items():
        for key in candidates:
            blobs, counts = {}, {}
            for y in years:
                try:
                    blobs[y] = _get(f"https://www.ncei.noaa.gov/pub/data/noaa/isd-lite/{y}/{key}-{y}.gz")
                    counts[y] = _isd_complete_rows(blobs[y])
                except Exception:
                    counts[y] = 0
            good_years = sum(c >= min_complete_per_year for c in counts.values())
            print(f"  {city} {key}: complete T/Td/SLP rows per year {counts}")
            if good_years >= 0.8 * len(list(years)):
                row = hist[hist.key == key].iloc[0]
                for y, b in blobs.items():
                    (out_dir / f"{key}-{y}.gz").write_bytes(b)
                chosen.append({"city": city, "name": f"{city} ({row['STATION NAME'].title()})",
                               "usaf": row["USAF"], "wban": row["WBAN"], "icao": row["ICAO"] if isinstance(row["ICAO"], str) else None,
                               "lat": float(row["LAT"]), "lon": float(row["LON"]), "elev_m": float(row["ELEV(M)"]),
                               "complete_rows_per_year": counts})
                break
        else:
            print(f"  {city}: no candidate met the completeness requirement — skipped")
    (out_dir / "stations.json").write_text(json.dumps({"years": list(years), "stations": chosen}, indent=2), encoding="utf-8")
    return out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download Layer 3 real weather datasets")
    ap.add_argument("dataset", choices=["open-meteo", "isd"])
    args = ap.parse_args(argv)
    if args.dataset == "open-meteo":
        print(f"Wrote {download_open_meteo()}")
    else:
        print(f"Wrote {download_isd()}")


if __name__ == "__main__":
    main()
