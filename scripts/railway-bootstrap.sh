#!/usr/bin/env bash
# Create/link a Railway service, set env, deploy, then copy local Tradebook.
# Requires: `railway login` already completed. Does not print secret values.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export FINLENS_ROOT="$ROOT"

if ! railway whoami >/dev/null 2>&1; then
  echo "Run: railway login" >&2
  exit 1
fi

if [ ! -f "$ROOT/.railway/config.json" ] && [ ! -f "$ROOT/railway.toml" ]; then
  :
fi

if [ ! -d "$ROOT/.railway" ]; then
  railway init --name FinLens --json
fi

railway add --repo AkashKhatrii/FinLens --branch main --service finlens --json || true
railway volume add --mount-path /var/data --json || true

"$ROOT/backend/.venv/bin/python" - <<PY
import os, subprocess
from pathlib import Path
from dotenv import dotenv_values

root = Path(os.environ["FINLENS_ROOT"])
vals = dotenv_values(root / "backend" / ".env")
password = os.urandom(12).hex()
(root / ".railway-password").write_text(password + "\\n")
pairs = {
    "FINLENS_DATA_DIR": "/var/data",
    "FINLENS_CACHE_DIR": "/var/data/cache",
    "FINLENS_PROVIDER": "deepseek",
    "FINLENS_PASSWORD": password,
}
for key in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID"):
    val = (vals.get(key) or "").strip()
    if val:
        pairs[key] = val
for key, value in pairs.items():
    subprocess.run(
        ["railway", "variable", "set", key, "--stdin", "--skip-deploys", "--json"],
        input=value.encode(),
        check=True,
    )
    print(f"set {key}")
print("password_file=.railway-password")
PY

railway up --yes --detach --json --message "Deploy FinLens" --service finlens || railway up --yes --detach --json --message "Deploy FinLens"
railway domain --json || true
"$ROOT/scripts/sync-tradebook.sh"
echo "Username: finlens"
echo "Password is in .railway-password (gitignored). Open the Railway domain and sign in."
