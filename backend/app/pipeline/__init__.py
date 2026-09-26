"""
ATHER real-time processing pipeline.

    source adapters ──> ingest (validate + normalize) ──> ObservationStream
        ──> ObservationProcessor (5-layer engine + fusion) ──> TimeSeriesStore
        ──> station health + incidents ──> EventBroker ──> SSE clients

See docs/REALTIME_ARCHITECTURE.md for the design and its scale-out path.
"""
