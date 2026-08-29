# V2.1 — Deployment Hardening

## Objective
Make Daily Store Control safe to deploy as a persistent browser application without losing SKU mappings or imported history after a container restart.

## Changes

### Persistent database
`app/v2_main.py` now reads `DSC_DB_PATH` from the environment. If not supplied it uses `data/daily_store_control.db`. The parent directory is created automatically.

### Render
`render.yaml` defines a Docker web service, health check, and a 1 GB persistent disk mounted at `/var/data`. `DSC_DB_PATH=/var/data/daily_store_control.db`.

### Railway
`railway.toml` uses the Dockerfile, starts via `run_app.sh`, and checks `/_stcore/health`. A persistent volume should be mounted and `DSC_DB_PATH` pointed to that volume.

### Docker
The image now:
- runs Python 3.12 slim;
- installs requirements;
- creates `/app/data`;
- starts via `run_app.sh`;
- exposes port 8501;
- has a Streamlit health check.

### Preflight
`python app/preflight.py` creates/opens a clean SQLite database, initializes schema, resolves the default store, and verifies core service queries.

## Verification
- Python compile: PASS
- Application preflight: PASS
- Regression tests: 23/23 PASS
- Actual Streamlit server boot in the build environment: not run because outbound network is disabled and Streamlit is not preinstalled. The deployment image installs Streamlit normally from `requirements.txt` when built on a hosting provider with network access.

## Source of truth remains unchanged
Control Profit is still reconstructed from Shopee Order + Shopee Income + HPP + all paid media. BigSeller store profit remains audit-only.
