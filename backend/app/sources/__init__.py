"""
Data-source adapters (spec §5).

    ObservationSourceAdapter
     ├── SimulationAdapter          SIMULATED_AWS telemetry for the WeatherUnion
     │                              AWS catalogue (dev/demo, fault injection)
     ├── NOAAISDAdapter             real hourly synoptic observations (opt-in)
     ├── WeatherUnionAdapter        real locality telemetry (needs API key)
     ├── IMDAWSAdapter              no public API — push via /api/observations
     └── OpenMeteoReferenceAdapter  NWP REFERENCE only; never an observation
"""
