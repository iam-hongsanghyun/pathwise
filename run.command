#!/usr/bin/env bash
# pathwise launcher — starts the backend (FastAPI/uvicorn) and the frontend
# (Vite), waits for the backend to be healthy, then opens the app. Double-click
# in Finder, or run ./run.command from a terminal.
set -euo pipefail
cd "$(dirname "$0")"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${PATHWISE_PORT:-8077}"
# Vite binds to `localhost` (often IPv6 ::1), so 127.0.0.1 can fail to load —
# open the frontend by its localhost name to match Vite's bind.
FRONTEND_HOST="localhost"
FRONTEND_PORT="5173"
FRONTEND_DIR="frontend/pathwise"
export PATHWISE_BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

cleanup() { echo; echo "▶ shutting down…"; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Stop any previous pathwise servers before starting — frees the backend and
# frontend ports and kills lingering uvicorn/vite instances (e.g. a stale
# backend left over from before an asset move), so every launch is clean.
echo "▶ stopping any previous pathwise servers…"
for port in "${BACKEND_PORT}" "${FRONTEND_PORT}"; do
  pids="$(lsof -ti "tcp:${port}" 2>/dev/null || true)"
  [ -n "${pids}" ] && kill ${pids} 2>/dev/null || true
done
pkill -f "uvicorn pathwise.api.main:app" 2>/dev/null || true
pkill -f "${FRONTEND_DIR}/node_modules/.bin/vite" 2>/dev/null || true
sleep 0.5

# Start from a clean slate: drop any persisted working sessions so the app opens
# empty on every launch. The browser keeps only a session-id pointer in
# localStorage; with its backend session gone the frontend transparently creates
# a fresh, empty one (see ensureSession in lib/api/session.ts).
DATA_DIR="${PATHWISE_DATA_DIR:-data}"
if [ -d "${DATA_DIR}/sessions" ]; then
  echo "▶ clearing previous sessions (${DATA_DIR}/sessions)…"
  rm -rf "${DATA_DIR}/sessions"
fi

if [ ! -d ".venv" ]; then
  echo "▶ installing backend deps (uv sync)…"
  uv sync --all-extras
fi
if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
  echo "▶ installing frontend deps (npm install)…"
  ( cd "${FRONTEND_DIR}" && npm install )
fi

echo "▶ backend  → http://${BACKEND_HOST}:${BACKEND_PORT}"
uv run uvicorn pathwise.api.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload &

echo "▶ frontend → http://${FRONTEND_HOST}:${FRONTEND_PORT}"
( cd "${FRONTEND_DIR}" && npm run dev -- --port "${FRONTEND_PORT}" ) &

echo -n "▶ waiting for backend"
for _ in $(seq 1 60); do
  if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    echo " ✓"; break
  fi
  echo -n "."; sleep 0.5
done

# Do not poll the frontend: Vite boots in <1s and the browser retries its own
# connection; polling 127.0.0.1 can hang because Vite binds to localhost.
URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
sleep 2
if command -v open >/dev/null 2>&1; then
  open "${URL}"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${URL}"
fi
echo "▶ open ${URL} (Ctrl-C to stop)"

wait
