"""
FastAPI application entrypoint for ATHER.
Serves the REST anomaly API and the real-time monitoring dashboard.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ather.api.routes import router as api_router, pipeline
from ather.api.ather_routes import ather_router, init_ather_routes
from ather.data.loader import JenaDataLoader
from ather.data.live_adapter import LiveWeatherAdapter

dashboard_dir = Path(__file__).parent.parent / "dashboard"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Fit multivariate models and calibrate conformal false alarm bound on Jena data
    print("Initializing ATHER pipeline and calibrating on Jena Climate dataset...", flush=True)
    try:
        loader = JenaDataLoader()
        clean_df = loader.load_dataframe(nrows=6000)
        pipeline.train_and_calibrate(clean_df, calibration_samples=1200)
        print("✓ Pipeline successfully calibrated with false alarm rate alpha <= 0.001.", flush=True)
    except Exception as e:
        print(f"Warning during calibration: {e}", flush=True)

    # Initialize live weather adapter for ATHER station routes
    print("Initializing live weather adapter for Indian AWS stations...", flush=True)
    live_adapter = LiveWeatherAdapter(cache_ttl_seconds=30)
    init_ather_routes(pipeline=pipeline, adapter=live_adapter)
    print(f"✓ Live adapter ready with {len(live_adapter.stations)} stations.", flush=True)

    yield
    print("Shutting down ATHER service...", flush=True)

app = FastAPI(
    title="ATHER — AWS Anomaly Detection API",
    description="5-Layer Anomaly Detection Engine for Automatic Weather Stations (SIH 2026)",
    version="0.2.0",
    lifespan=lifespan
)

# CORS middleware for open integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes (existing + new ATHER live routes)
app.include_router(api_router)
app.include_router(ather_router)

# Mount Dashboard Static files if directory exists
if dashboard_dir.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")

@app.get("/")
def serve_dashboard():
    index_path = dashboard_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ATHER API is operational. Navigate to /docs for OpenAPI documentation."}
