"""
Real-time source check for Layer 3.

ATHER's live values for its 296 WeatherUnion AWS locations come from the
Open-Meteo FORECAST API (see app/weather/open_meteo.py). This check pulls the
last `past_days` of hourly values for exactly those coordinates from the same
API, replays each station chronologically through the production Layer 3
path (MultivariateConsistencyLayer with regional reference models and trust
gating, exactly as detector.py calls it), and reports:

  - how often each decision tier fires on presumed-normal live-source data
    (an alarm RATE — there are no labels; it also exposes any systematic
    mismatch between the live forecast feed and the reanalysis the reference
    models were trained on)
  - one controlled T-RH decoupling event per station, built only from that
    station's own live values (a warm afternoon given the station's own
    night-time median RH), and whether Layer 3 flags it

    python -m multivariate.live_check            # fetches and caches the feed
    python -m multivariate.live_check --cached   # re-uses the cached CSV
"""
import argparse
import copy
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from config import CONFIG
from multivariate.download import USER_AGENT

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND_DIR / "reports" / "multivariate"
FEED_CSV = OUT_DIR / "live_feed_open_meteo_forecast.csv"


def load_weatherunion_stations() -> pd.DataFrame:
    w = pd.read_csv(BACKEND_DIR / "WeatherUnionInfra.csv")
    w = w[w["device_type"].astype(str).str.contains("Automated weather system")]
    w = w[w["latitude"].between(6, 38) & w["longitude"].between(68, 98)]
    return w.drop_duplicates("localityId")[["localityId", "cityName", "latitude", "longitude"]].reset_index(drop=True)


def fetch_feed(stations: pd.DataFrame, past_days: int = 7, chunk: int = 50) -> pd.DataFrame:
    frames = []
    for i in range(0, len(stations), chunk):
        part = stations.iloc[i:i + chunk]
        url = ("https://api.open-meteo.com/v1/forecast?"
               f"latitude={','.join(f'{v:.4f}' for v in part.latitude)}&longitude={','.join(f'{v:.4f}' for v in part.longitude)}"
               f"&hourly=temperature_2m,relative_humidity_2m,pressure_msl&past_days={past_days}&forecast_days=1")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        raw = json.loads(urllib.request.urlopen(req, timeout=60).read())
        raw = raw if isinstance(raw, list) else [raw]
        for (_, st), item in zip(part.iterrows(), raw):
            h = item["hourly"]
            frames.append(pd.DataFrame({
                "station_id": str(st.localityId), "city": st.cityName, "latitude": st.latitude, "longitude": st.longitude,
                "timestamp": pd.to_datetime(h["time"]).tz_localize("UTC"),     # API default timezone is GMT
                "temperature_c": h["temperature_2m"], "humidity_pct": h["relative_humidity_2m"],
                "pressure_hpa": h["pressure_msl"]}))
        time.sleep(1.0)
    df = pd.concat(frames, ignore_index=True)
    return df[df["timestamp"] <= pd.Timestamp.now(tz="UTC")].dropna()


def _replay_city(city_df: pd.DataFrame, inject: bool):
    from schema import AWSReading, ObservationSource
    from engine.layer3_multivariate import MultivariateConsistencyLayer
    layer = MultivariateConsistencyLayer(config=copy.deepcopy(CONFIG.multivariate))
    out = []
    for sid, g in city_df.groupby("station_id"):
        g = g.sort_values("timestamp").reset_index(drop=True)
        g["is_injected"] = False
        if inject:
            solar = (g.timestamp.dt.hour + g.longitude / 15.0) % 24
            night_rh = g.loc[solar < 5, "humidity_pct"].median()
            # a warm-afternoon window in the last 3 days, 6 consecutive hours
            cand = g.index[(solar.between(12, 13)) & (g.index > len(g) - 72) & (g.index < len(g) - 7)]
            if len(cand) and night_rh - g.loc[cand[0]:cand[0] + 5, "humidity_pct"].max() >= 15:
                rows = range(cand[0], cand[0] + 6)
                g.loc[rows, "humidity_pct"] = round(night_rh)
                g.loc[rows, "is_injected"] = True
        for r in g.itertuples():
            reading = AWSReading(station_id=sid, lat=r.latitude, lon=r.longitude, temperature_c=r.temperature_c,
                                 pressure_hpa=r.pressure_hpa, humidity_pct=r.humidity_pct,
                                 observation_timestamp=r.timestamp.to_pydatetime(), source=ObservationSource.NWP_MODEL_REFERENCE)
            score, reason, d = layer.evaluate(reading)
            dec = d.get("decision") or {}
            out.append({"station_id": sid, "city": r.city, "timestamp": r.timestamp, "is_injected": r.is_injected,
                        "temperature_c": r.temperature_c, "pressure_hpa": r.pressure_hpa, "humidity_pct": r.humidity_pct,
                        "method": d.get("method"), "model_source": d.get("model_source"),
                        "reference_site": d.get("reference_site"), "status": dec.get("status", "NO_MODEL"),
                        "ecod_p": (d.get("ecod") or {}).get("p_value"), "if_p": (d.get("isolation_forest") or {}).get("p_value"),
                        "layer_score": score, "reason": reason})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", action="store_true")
    ap.add_argument("--past-days", type=int, default=7)
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.cached and FEED_CSV.exists():
        feed = pd.read_csv(FEED_CSV, parse_dates=["timestamp"])
    else:
        feed = fetch_feed(load_weatherunion_stations(), args.past_days)
        feed.to_csv(FEED_CSV, index=False)
    print(f"[feed] {len(feed)} hourly readings, {feed.station_id.nunique()} stations, "
          f"{feed.timestamp.min()} .. {feed.timestamp.max()} (Open-Meteo forecast API, NWP_MODEL_REFERENCE)")

    report = {"feed": {"rows": int(len(feed)), "stations": int(feed.station_id.nunique()),
                       "start": str(feed.timestamp.min()), "end": str(feed.timestamp.max())}}
    for inject in (False, True):
        res = pd.DataFrame([r for chunk in Parallel(n_jobs=-2)(
            delayed(_replay_city)(g, inject) for _, g in feed.groupby("city")) for r in chunk])
        key = "injected_t_rh_decoupling" if inject else "normal_live_feed"
        # skip the first observation of each station (no previous obs to form deltas; same as production)
        if not inject:
            rate = res.groupby("city")["status"].value_counts(normalize=True).unstack(fill_value=0).round(4)
            report[key] = {
                "observations": int(len(res)),
                "model_source": res["model_source"].value_counts().to_dict(),
                "status_rate": res["status"].value_counts(normalize=True).round(5).to_dict(),
                "status_count": res["status"].value_counts().to_dict(),
                "status_rate_by_city": rate.to_dict(orient="index"),
                "examples_flagged": res[res.status != "NORMAL"].head(8)[["station_id", "city", "timestamp", "temperature_c",
                                                                          "pressure_hpa", "humidity_pct", "status", "reason"]]
                .astype(str).to_dict(orient="records"),
            }
            print("\n[normal live-source replay] status rates:", report[key]["status_rate"])
            print(rate.to_string())
        else:
            inj = res[res.is_injected]
            ev = inj.groupby("station_id")["status"].apply(lambda s: (s != "NORMAL").any())
            report[key] = {
                "stations_with_event": int(ev.size), "injected_rows": int(len(inj)),
                "row_recall_any_flag": round(float((inj.status != "NORMAL").mean()), 4) if len(inj) else None,
                "row_recall_anomaly": round(float((inj.status == "ANOMALY").mean()), 4) if len(inj) else None,
                "event_recall_any_flag": round(float(ev.mean()), 4) if len(ev) else None,
                "examples": inj[inj.status != "NORMAL"].head(6)[["station_id", "city", "timestamp", "temperature_c",
                                                                "humidity_pct", "status", "ecod_p", "if_p", "reason"]]
                .astype(str).to_dict(orient="records"),
            }
            print("\n[injected T-RH decoupling on live-source data]", {k: v for k, v in report[key].items() if k != "examples"})
    (OUT_DIR / "live_feed_check.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n[report] {OUT_DIR / 'live_feed_check.json'}")


if __name__ == "__main__":
    main()
