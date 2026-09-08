"""
ATHER Weather Grid Service
--------------------------
Generates gridded meteorological fields (Temperature, Wind U/V vectors, Pressure)
compatible with Vane's WebGL colormap and particle streamlines.
"""

import math
from typing import Dict, Any

class WeatherGridService:
    def __init__(self):
        # We define a global regular grid (e.g. 72 x 36 points covering [-180..180], [-85..85])
        self.nx = 72
        self.ny = 36
        self.lon_min = -180.0
        self.lon_max = 180.0
        self.lat_min = -85.0
        self.lat_max = 85.0

    def get_grid_metadata(self) -> Dict[str, Any]:
        return {
            "source": "ATHER Meteorological Grid Engine / Vane Adapter",
            "model_run": "2026-09-08T12:00:00Z",
            "bbox": [self.lon_min, self.lat_min, self.lon_max, self.lat_max],
            "nx": self.nx,
            "ny": self.ny,
            "variables": {
                "temperature": {"unit": "°C", "clim": [-30.0, 45.0]},
                "wind": {"unit": "m/s", "vector_group": "wind", "speed_range": [0, 25]},
                "pressure_msl": {"unit": "hPa", "clim": [980.0, 1040.0]},
                "humidity": {"unit": "%", "clim": [10.0, 100.0]}
            }
        }

    def generate_temperature_field(self) -> Dict[str, Any]:
        """
        Generates realistic global surface temperature field based on latitude bands,
        solar declination, land/sea thermal contrast, and atmospheric wave patterns.
        """
        data = []
        for j in range(self.ny):
            lat = self.lat_max - j * ((self.lat_max - self.lat_min) / (self.ny - 1))
            # Latitudinal baseline (warm at equator ~30°C, cold at poles ~ -25°C)
            rad_lat = math.radians(lat)
            base_t = 30.0 * math.cos(rad_lat) - 15.0 * (math.sin(rad_lat) ** 2)

            for i in range(self.nx):
                lon = self.lon_min + i * ((self.lon_max - self.lon_min) / (self.nx - 1))
                rad_lon = math.radians(lon)

                # Rossby planetary wave modulation (wavenumber 3)
                planetary_wave = 4.0 * math.sin(3 * rad_lon + rad_lat * 2.0)
                # Continental/oceanic thermal perturbation
                continent_effect = 3.5 * math.sin(rad_lon * 2.0) * math.cos(rad_lat)

                temp = round(base_t + planetary_wave + continent_effect, 2)
                data.append(temp)

        return {
            "variable": "temperature",
            "unit": "°C",
            "clim": [-30.0, 45.0],
            "nx": self.nx,
            "ny": self.ny,
            "bbox": [self.lon_min, self.lat_min, self.lon_max, self.lat_max],
            "data": data
        }

    def generate_wind_field(self) -> Dict[str, Any]:
        """
        Generates global U (eastward) and V (northward) vector fields reflecting
        global atmospheric circulation cells (Hadley, Ferrel, Polar, Trade winds, Westerlies).
        """
        u_data = []
        v_data = []
        for j in range(self.ny):
            lat = self.lat_max - j * ((self.lat_max - self.lat_min) / (self.ny - 1))
            rad_lat = math.radians(lat)

            # Zonal wind profile (Trade winds: easterly (negative U), Westerlies: strong positive U)
            # Mid-latitude jet streams near 45°N and 45°S
            if abs(lat) < 25:
                # Tropical trade winds (blow east to west -> u < 0)
                zonal_u = -6.0 * math.cos(rad_lat * 3.6)
                meridional_v = -2.0 * math.copysign(1.0, lat)
            elif abs(lat) < 60:
                # Mid-latitude westerlies (blow west to east -> u > 0)
                zonal_u = 12.0 * math.sin(rad_lat * 2.5) ** 2
                meridional_v = 3.0 * math.sin(rad_lat * 4.0)
            else:
                # Polar easterlies
                zonal_u = -4.0 * math.cos(rad_lat)
                meridional_v = -1.0 * math.copysign(1.0, lat)

            for i in range(self.nx):
                lon = self.lon_min + i * ((self.lon_max - self.lon_min) / (self.nx - 1))
                rad_lon = math.radians(lon)

                # Cyclonic and anticyclonic eddies
                eddy_u = 3.0 * math.sin(5 * rad_lon) * math.sin(3 * rad_lat)
                eddy_v = 3.0 * math.cos(5 * rad_lon) * math.cos(3 * rad_lat)

                u = round(zonal_u + eddy_u, 2)
                v = round(meridional_v + eddy_v, 2)

                u_data.append(u)
                v_data.append(v)

        return {
            "variable": "wind",
            "unit": "m/s",
            "nx": self.nx,
            "ny": self.ny,
            "bbox": [self.lon_min, self.lat_min, self.lon_max, self.lat_max],
            "u": u_data,
            "v": v_data
        }

grid_service = WeatherGridService()
