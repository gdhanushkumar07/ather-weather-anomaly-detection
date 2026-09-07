"""
Main CLI Launcher for ATHER (SkyGuard AI).
Starts the FastAPI backend and real-time Glassmorphic monitoring dashboard.
"""
import sys
import uvicorn

def main():
    print("=" * 70)
    print("      ATHER (SkyGuard AI) — SIH 2026 AWS ANOMALY DETECTION")
    print("=" * 70)
    print(" Starting API & Interactive Dashboard at http://localhost:8000 ...")
    print(" Press Ctrl+C to stop.")
    print("=" * 70)

    uvicorn.run("ather.api.main:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
