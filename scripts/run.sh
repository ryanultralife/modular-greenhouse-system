#!/usr/bin/env bash
# Launch the Modular Greenhouse System backend + admin UI.
set -euo pipefail
cd "$(dirname "$0")/.."

# Install deps on first run (idempotent).
python3 -m pip install -q -r requirements.txt

# A master key for encrypting integration secrets. If you don't set
# MGS_SECRET_KEY here, one is generated and stored in data/.secret_key
# (git-ignored) on first run.
exec python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8000 "$@"
