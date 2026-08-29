#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export DSC_DB_PATH="${DSC_DB_PATH:-$(pwd)/data/daily_store_control.db}"
mkdir -p "$(dirname "$DSC_DB_PATH")"
exec streamlit run app/v2_main.py --server.address=0.0.0.0 --server.port="${PORT:-8501}"
