#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Starting Report Updater v3..."

PYTHON_BIN=""

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif [ -d ".venv" ] && [ -d ".venv/Scripts" ]; then
  echo "[INFO] Detected a Windows virtual environment in .venv; using the local Linux Python instead."
fi

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[ERROR] Python is not installed or not available on PATH."
    exit 1
  fi
fi

if [ ! -f "app.py" ]; then
  echo "[ERROR] app.py was not found in $(pwd)"
  exit 1
fi

export STREAMLIT_BROWSER_GATHER_USAGE_STATS="${STREAMLIT_BROWSER_GATHER_USAGE_STATS:-false}"
export STREAMLIT_SERVER_HEADLESS="${STREAMLIT_SERVER_HEADLESS:-true}"
export STREAMLIT_SERVER_ADDRESS="${STREAMLIT_SERVER_ADDRESS:-0.0.0.0}"
export STREAMLIT_SERVER_PORT="${STREAMLIT_SERVER_PORT:-8501}"

exec "$PYTHON_BIN" -m streamlit run app.py \
  --server.headless "$STREAMLIT_SERVER_HEADLESS" \
  --server.address "$STREAMLIT_SERVER_ADDRESS" \
  --server.port "$STREAMLIT_SERVER_PORT" \
  --browser.gatherUsageStats "$STREAMLIT_BROWSER_GATHER_USAGE_STATS"
