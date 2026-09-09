"""
Main CLI Launcher for ATHER (SkyGuard AI).
Starts the FastAPI backend and real-time Glassmorphic monitoring dashboard.
"""
import argparse
import uvicorn

def main():
    parser = argparse.ArgumentParser(description="Start ATHER API and Dashboard.")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind")
    args = parser.parse_args()

    print("=" * 70)
    print("      ATHER (SkyGuard AI) — SIH 2026 AWS ANOMALY DETECTION")
    print("=" * 70)
    print(f" Starting API & Interactive Dashboard at http://localhost:{args.port} ...")
    print(" Press Ctrl+C to stop.")
    print("=" * 70)

    uvicorn.run("ather.api.main:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
