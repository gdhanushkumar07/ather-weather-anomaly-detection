"""
ATHER Multi-Protocol Ingestion Adapter
--------------------------------------
Adapts telemetry payloads from WeeWX, WOW-BE, Weather Underground, and native ATHER API.
"""

from typing import Dict, Any, Optional, Tuple

_DECLARABLE_CONVENTIONS = ("MSL", "SURFACE")


def declared_pressure_convention(data: Dict[str, Any]) -> Optional[str]:
    """The pressure convention a payload EXPLICITLY declares, or None.

    Only "MSL" (sea-level-reduced) or "SURFACE" (station pressure) are accepted,
    case-insensitively; anything else, or no declaration, is None (UNKNOWN).

    PROVENANCE POLICY: none of the supported third-party formats (WeeWX
    `barometer`, Weather Underground / WOW `baromin`/`barometer`, the native
    format's `pressure`) is assumed to have a particular convention by this
    adapter -- their vendor documentation is not encoded here, so a convention is
    recorded only when the sender states it. Nothing is inferred from magnitude.
    """
    value = data.get("pressureConvention")
    if isinstance(value, str) and value.strip().upper() in _DECLARABLE_CONVENTIONS:
        return value.strip().upper()
    return None


class IngestionAdapter:
    @staticmethod
    def parse_payload(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Normalizes input payload from any supported format into ATHER standard:
        Returns (station_id, normalized_dict).
        """
        # 1. Native ATHER format
        if "id" in data:
            stn_id = str(data["id"])
            return stn_id, {
                "temperature": data.get("temperature"),
                "pressure": data.get("pressure"),
                "pressureConvention": declared_pressure_convention(data),
                "humidity": data.get("humidity"),
                "windSpeed": data.get("windSpeed"),
                "windDirection": data.get("windDirection"),
                "condition": data.get("condition", "Reported")
            }

        # 2. Weather Underground / WOW-BE format
        if "ID" in data or "siteid" in data:
            stn_id = str(data.get("ID") or data.get("siteid"))
            temp_c = None
            if "tempf" in data:
                try:
                    temp_c = round((float(data["tempf"]) - 32) * 5 / 9, 1)
                except (ValueError, TypeError):
                    pass
            elif "temp" in data:
                temp_c = float(data["temp"])

            press_hpa = None
            if "baromin" in data:
                try:
                    press_hpa = round(float(data["baromin"]) * 33.8639, 1)
                except (ValueError, TypeError):
                    pass
            elif "barometer" in data:
                press_hpa = float(data["barometer"])

            wind_kmh = None
            if "windspeedmph" in data:
                try:
                    wind_kmh = round(float(data["windspeedmph"]) * 1.60934, 1)
                except (ValueError, TypeError):
                    pass

            humidity = None
            if "humidity" in data:
                try:
                    humidity = int(round(float(data["humidity"])))
                except (ValueError, TypeError):
                    pass

            return stn_id, {
                "temperature": temp_c,
                "pressure": press_hpa,
                "pressureConvention": declared_pressure_convention(data),
                "humidity": humidity,
                "windSpeed": wind_kmh,
                "windDirection": str(data.get("winddir", "VAR")),
                "condition": "Reported"
            }

        # 3. WeeWX driver format
        if "outTemp" in data or "dateTime" in data:
            stn_id = str(data.get("station_id", "ATHER-WEEWX-01"))
            out_temp = data.get("outTemp")
            # If in Fahrenheit (>50 usually in US customary units)
            temp_c = round((out_temp - 32) * 5 / 9, 1) if (out_temp is not None and data.get("unit_system") == "US") else out_temp

            barometer = data.get("barometer")
            press_hpa = round(barometer * 33.8639, 1) if (barometer is not None and data.get("unit_system") == "US") else barometer

            wind_speed = data.get("windSpeed")
            wind_kmh = round(wind_speed * 1.60934, 1) if (wind_speed is not None and data.get("unit_system") == "US") else wind_speed

            return stn_id, {
                "temperature": temp_c,
                "pressure": press_hpa,
                "pressureConvention": declared_pressure_convention(data),
                "humidity": data.get("outHumidity"),
                "windSpeed": wind_kmh,
                "windDirection": str(data.get("windDir", "CALM")),
                "condition": "WeeWX Ingest"
            }

        raise ValueError("Unrecognized ingestion payload format.")
