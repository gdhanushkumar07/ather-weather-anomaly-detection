#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "          STARTING ATHER METEOROLOGICAL PLATFORM             "
echo "============================================================"

# 1. Start FastAPI Backend on Port 8000
echo "[1/2] Launching ATHER Backend (FastAPI on http://localhost:8000)..."
python3 "$DIR/backend/run.py" &
BACKEND_PID=$!

# Ensure backend stops when script exits
trap "kill $BACKEND_PID 2>/dev/null || true" EXIT

sleep 2

# 2. Start Vite Frontend on Port 3000
echo "[2/2] Launching ATHER Frontend (Vite on http://localhost:3000)..."
cd "$DIR/frontend"
npm run dev

wait $BACKEND_PID
