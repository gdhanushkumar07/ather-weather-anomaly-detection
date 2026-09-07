"""
Dataset loaders for Jena Climate 2009-2016 and Open-Meteo API.
"""
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional, Tuple
import pandas as pd
import requests

from ather.config import CONFIG
from ather.data.schema import AWSReading

class JenaDataLoader:
    """
    Parser and stream iterator for the Max Planck Institute Jena Climate dataset.
    """
    def __init__(
        self,
        csv_path: str = "jena_climate_2009_2016.csv",
        station_id: str = CONFIG.default_station_id,
        lat: float = CONFIG.default_lat,
        lon: float = CONFIG.default_lon,
        elevation_m: float = CONFIG.default_elevation_m
    ):
        self.csv_path = Path(csv_path)
        self.station_id = station_id
        self.lat = lat
        self.lon = lon
        self.elevation_m = elevation_m

        if not self.csv_path.exists():
            raise FileNotFoundError(f"Jena climate dataset not found at: {self.csv_path.resolve()}")

    def load_dataframe(self, nrows: Optional[int] = None) -> pd.DataFrame:
        """
        Loads and standardizes Jena climate CSV into a clean DataFrame.
        """
        cols_needed = ["Date Time", "p (mbar)", "T (degC)", "rh (%)", "Tdew (degC)"]
        df = pd.read_csv(self.csv_path, usecols=cols_needed, nrows=nrows)

        # Standardize column naming
        df = df.rename(columns={
            "Date Time": "timestamp",
            "p (mbar)": "pressure_hpa",
            "T (degC)": "temperature_c",
            "rh (%)": "humidity_pct",
            "Tdew (degC)": "dew_point_c"
        })

        # Parse timestamps (format: 01.01.2009 00:10:00)
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%d.%m.%Y %H:%M:%S")

        df["station_id"] = self.station_id
        df["lat"] = self.lat
        df["lon"] = self.lon
        df["elevation_m"] = self.elevation_m

        # Ensure sorted chronologically
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def stream_readings(
        self,
        start_idx: int = 0,
        count: Optional[int] = None
    ) -> Generator[AWSReading, None, None]:
        """
        Yields normalized AWSReading objects sequentially to simulate live AWS telemetry.
        """
        df = self.load_dataframe(nrows=None if count is None else start_idx + count)
        if start_idx > 0:
            df = df.iloc[start_idx:]
        if count is not None:
            df = df.iloc[:count]

        for _, row in df.iterrows():
            yield AWSReading(
                station_id=row["station_id"],
                timestamp=row["timestamp"].to_pydatetime(),
                temperature_c=float(row["temperature_c"]),
                pressure_hpa=float(row["pressure_hpa"]),
                humidity_pct=float(row["humidity_pct"]),
                dew_point_c=float(row["dew_point_c"]) if pd.notna(row["dew_point_c"]) else None,
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                elevation_m=float(row["elevation_m"])
            )


class OpenMeteoLoader:
    """
    Fetches real multi-station hourly observations from Open-Meteo's free Archive API.
    Used for multi-station spatial network simulation without requiring an API key.
    """
    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

    @classmethod
    def fetch_station_data(
        cls,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
        station_id: str = "OPEN_METEO_01"
    ) -> pd.DataFrame:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ["temperature_2m", "relative_humidity_2m", "surface_pressure", "dew_point_2m"],
            "timezone": "UTC"
        }
        resp = requests.get(cls.BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()["hourly"]

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data["time"]),
            "temperature_c": data["temperature_2m"],
            "pressure_hpa": data["surface_pressure"],
            "humidity_pct": data["relative_humidity_2m"],
            "dew_point_c": data["dew_point_2m"]
        })
        df["station_id"] = station_id
        df["lat"] = lat
        df["lon"] = lon
        df["elevation_m"] = resp.json().get("elevation", 0.0)
        return df
