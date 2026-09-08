#!/usr/bin/env python3
"""
Simulate live weather station telemetry updates (WeeWX / WOW / Native format)
to demonstrate real-time anomaly detection in ATHER.
"""

import time
import requests
import random

API_URL = "http://localhost:8000/api/ingest"

DEMO_STATIONS = [
    {
        "id": "ATHER-001",
        "name": "ATHER Reference Station Alpha",
        "town": "Hyderabad, Telangana, India",
        "temp_normal": 29.5,
        "press_normal": 1008.0
    },
    {
        "id": "ATHER-IND-003",
        "name": "ATHER Delhi Metro Observatory",
        "town": "New Delhi, NCR, India",
        "temp_normal": 34.0,
        "press_normal": 1004.0
    },
    {
        "id": "ATHER-USA-010",
        "name": "Boulder Atmospheric Observatory",
        "town": "Boulder, Colorado, USA",
        "temp_normal": 21.0,
        "press_normal": 840.0
    }
]

def run_simulation():
    print(f"Starting ATHER Live Telemetry Ingestion Simulator -> {API_URL}")
    step = 0
    while True:
        step += 1
        stn = random.choice(DEMO_STATIONS)
        
        # Every 4th tick, inject an anomaly
        is_spike = (step % 4 == 0)
        
        if is_spike:
            # Thermal spike anomaly
            temp = round(stn["temp_normal"] + random.uniform(8.0, 14.0), 1)
            print(f"\n[ALERT] Injecting ANOMALY spike into {stn['id']} ({stn['name']}): {temp}°C")
        else:
            temp = round(stn["temp_normal"] + random.uniform(-1.5, 1.5), 1)
            print(f"\n[INFO] Sending normal telemetry update for {stn['id']}: {temp}°C")

        payload = {
            "id": stn["id"],
            "temperature": temp,
            "pressure": round(stn["press_normal"] + random.uniform(-2, 2), 1),
            "humidity": random.randint(40, 75),
            "windSpeed": round(random.uniform(5.0, 25.0), 1),
            "windDirection": random.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),
            "condition": "Scattered Clouds" if not is_spike else "Extreme Heat Advisory"
        }

        try:
            res = requests.post(API_URL, json=payload, timeout=3)
            data = res.json()
            stn_state = data.get("station", {})
            print(f"Status returned: {stn_state.get('status')} | Anomaly: {stn_state.get('anomaly') is not None}")
        except Exception as e:
            print(f"Ingestion error: {e}")

        time.sleep(10)

if __name__ == "__main__":
    run_simulation()
