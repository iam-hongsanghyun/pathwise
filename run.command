#!/usr/bin/env bash
# Dev launcher: starts the FastAPI backend (uvicorn :8000) and the Vite
# frontend (:5173). The frontend dev server proxies /api → :8000.
set -euo pipefail
cd "$(dirname "$0")"

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT

echo "▶ backend  → http://127.0.0.1:8000"
uv run uvicorn pathwise.api.main:app --host 127.0.0.1 --port 8000 --reload &

echo "▶ frontend → http://127.0.0.1:5173"
( cd frontend/pathwise_default && npm run dev ) &

wait
