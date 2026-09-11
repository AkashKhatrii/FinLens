#!/usr/bin/env bash
# Start FinLens on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/backend"
[ -d .venv ] || /opt/homebrew/bin/python3.12 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
exec ./.venv/bin/uvicorn app.main:app --reload --port "${PORT:-8000}"
