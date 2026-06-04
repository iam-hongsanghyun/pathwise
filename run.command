#!/usr/bin/env bash
# pathwise launcher — starts the backend (FastAPI/uvicorn) and the frontend
# (Vite), waits until the backend is healthy, and opens the app in a browser.
# Double-click in Finder, or run ./run.command from a terminal.
set -euo pipefail
cd "$(dirname "$0")"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${PATHWISE_PORT:-8077}"   # 8000 is often taken (e.g. pypsa)
FRONTEND_PORT="5173"
FRONTEND_DIR="frontend/pathwise_default"
# Keep the Vite proxy in sync with the backend port (no drift).
export PATHWISE_BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

cleanup() { echo; echo "▶ shutting down…"; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 1) First-run dependency install (idempotent).
if [ ! -d ".venv" ]; then
  echo "▶ installing backend deps (uv sync)…"
  uv sync --all-extras
fi
if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
  echo "▶ installing frontend deps (npm install)…"
  ( cd "${FRONTEND_DIR}" && npm install )
fi

# 2) Backend.
echo "▶ backend  → http://${BACKEND_HOST}:${BACKEND_PORT}"
uv run uvicorn pathwise.api.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload &

# 3) Frontend.
echo "▶ frontend → http://${BACKEND_HOST}:${FRONTEND_PORT}"
( cd "${FRONTEND_DIR}" && npm run dev -- --port "${FRONTEND_PORT}" ) &

# 4) Wait for the backend to answer.
echo -n "▶ waiting for backend"
for _ in $(seq 1 60); do
  if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  echo -n "."
  sleep 0.5
done

# 5) Open the browser. We do NOT poll the frontend: Vite binds to `localhost`
# (often IPv6 ::1) so a curl probe on 127.0.0.1 can hang forever even though the
# dev server is up. Vite boots in well under a second; the browser retries its
# own connection, so just give it a brief settle and open.
URL="http://${BACKEND_HOST}:${FRONTEND_PORT}"
sleep 2
if command -v open >/dev/null 2>&1; then
  open "${URL}"          # macOS
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${URL}"      # Linux
fi
echo "▶ open ${URL} (Ctrl-C to stop)"

wait
