#!/usr/bin/env bash
# Copy local Tradebook JSON onto the Railway volume (does not go through git).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/backend/.data/tradebook"
if [ ! -d "$SRC" ]; then
  echo "No local Tradebook at $SRC" >&2
  exit 1
fi
if ! command -v railway >/dev/null; then
  echo "Install the Railway CLI first: brew install railway" >&2
  exit 1
fi
echo "Uploading $(ls -1 "$SRC"/*.json | wc -l | tr -d ' ') snapshots to /tradebook"
VOLUME="${RAILWAY_VOLUME:-finlens-volume}"
for f in "$SRC"/*.json; do
  name="$(basename "$f")"
  railway volume files --volume "$VOLUME" upload "$f" "/tradebook/$name" --json >/dev/null
  echo "  $name"
done
echo "Done. App reads them from \$FINLENS_DATA_DIR/tradebook (mounted at /var/data/tradebook)."
