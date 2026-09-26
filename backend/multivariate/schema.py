"""
Standard observation schema for Layer 3.

Every dataset adapter maps its raw columns onto exactly these names, so no
dataset-specific column name ever reaches feature engineering or the models.

    station_id     str
    timestamp      tz-aware UTC pandas Timestamp
    temperature_c  float, air temperature at ~2 m
    pressure_hpa   float, MEAN-SEA-LEVEL pressure (what ATHER's live
                   Open-Meteo feed reports as `pressure`)
    humidity_pct   float, relative humidity [0, 100]
    latitude       float (optional but needed for the regional reference)
    longitude      float (needed for local-solar-hour features)
"""
STATION_ID = "station_id"
TIMESTAMP = "timestamp"
TEMPERATURE = "temperature_c"
PRESSURE = "pressure_hpa"
HUMIDITY = "humidity_pct"
LATITUDE = "latitude"
LONGITUDE = "longitude"

CHANNELS = [TEMPERATURE, PRESSURE, HUMIDITY]
REQUIRED_COLUMNS = [STATION_ID, TIMESTAMP] + CHANNELS
