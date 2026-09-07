"""
Multi-station synthetic network generator for spatial consistency evaluation.
Simulates a cluster of correlated AWS nodes with realistic atmospheric lapse rates and elevation offsets.
"""
from typing import Dict, List
import numpy as np
import pandas as pd

from ather.data.schema import AWSReading, StationMetadata

class StationNetworkSimulator:
    """
    Simulates a network of geographically adjacent AWS stations derived from a base reference station.
    """
    def __init__(self, base_df: pd.DataFrame):
        self.base_df = base_df.copy()

        # Define 4 neighboring stations in Thuringia around Jena
        self.stations: Dict[str, StationMetadata] = {
            "AWS_JENA_01": StationMetadata(
                station_id="AWS_JENA_01",
                name="Jena Central Observatory",
                lat=50.93,
                lon=11.58,
                elevation_m=207.0
            ),
            "AWS_JENA_NORTH": StationMetadata(
                station_id="AWS_JENA_NORTH",
                name="Jena North Valley",
                lat=51.05,
                lon=11.60,
                elevation_m=165.0
            ),
            "AWS_JENA_EAST": StationMetadata(
                station_id="AWS_JENA_EAST",
                name="Jena East Plateau",
                lat=50.90,
                lon=11.75,
                elevation_m=285.0
            ),
            "AWS_THURINGIA_SOUTH": StationMetadata(
                station_id="AWS_THURINGIA_SOUTH",
                name="Thuringian Ridge Station",
                lat=50.75,
                lon=11.45,
                elevation_m=420.0
            )
        }

    def generate_station_readings(self, station_id: str) -> pd.DataFrame:
        """
        Derives correlated physical observations for a neighbor station using thermodynamic lapse rate.
        """
        meta = self.stations[station_id]
        base_meta = self.stations["AWS_JENA_01"]
        delta_h = meta.elevation_m - base_meta.elevation_m

        df = self.base_df.copy()
        df["station_id"] = meta.station_id
        df["lat"] = meta.lat
        df["lon"] = meta.lon
        df["elevation_m"] = meta.elevation_m

        # 1. Temperature lapse rate: ~ -6.5 K / 1000m
        temp_offset = -0.0065 * delta_h
        # Add small microclimate noise
        rng = np.random.default_rng(abs(hash(station_id)) % (2**32))
        noise_t = rng.normal(0, 0.35, size=len(df))
        df["temperature_c"] = df["temperature_c"] + temp_offset + noise_t

        # 2. Barometric pressure height equation: P = P0 * exp(- M g dh / R T)
        # dh in meters, ~12 Pa / m near surface (~0.12 hPa/m)
        pressure_offset = -0.12 * delta_h
        noise_p = rng.normal(0, 0.15, size=len(df))
        df["pressure_hpa"] = df["pressure_hpa"] + pressure_offset + noise_p

        # 3. Humidity variation
        noise_rh = rng.normal(0, 1.5, size=len(df))
        df["humidity_pct"] = np.clip(df["humidity_pct"] + noise_rh, 5.0, 100.0)

        return df

    def get_all_stations_at_timestamp(self, timestamp: pd.Timestamp) -> List[AWSReading]:
        """
        Returns synchronized AWSReading for all network stations at a specific timestamp.
        """
        readings = []
        for s_id in self.stations:
            st_df = self.generate_station_readings(s_id)
            row = st_df[st_df["timestamp"] == timestamp]
            if not row.empty:
                r = row.iloc[0]
                readings.append(
                    AWSReading(
                        station_id=r["station_id"],
                        timestamp=r["timestamp"].to_pydatetime(),
                        temperature_c=float(r["temperature_c"]),
                        pressure_hpa=float(r["pressure_hpa"]),
                        humidity_pct=float(r["humidity_pct"]),
                        lat=float(r["lat"]),
                        lon=float(r["lon"]),
                        elevation_m=float(r["elevation_m"])
                    )
                )
        return readings
