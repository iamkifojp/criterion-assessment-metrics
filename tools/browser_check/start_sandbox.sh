#!/bin/zsh
# Start CAM from a sandbox copy for the Phase 4 browser checks (Mac).
#
#   zsh tools/browser_check/start_sandbox.sh [sandbox folder]
#
# The same as start_sandbox.ps1: tracked files only, the Mac bundle's exact
# libraries in a sandbox venv, every data path in the sandbox, port 8611.
# See README.md here.
set -eu
REPO=${0:A:h:h:h}
SB=${1:-${TMPDIR:-/tmp}/cam-browser-sb}
mkdir -p "$SB"/{repo,data,home,cam2data,docs,docs2}
cd "$REPO"
git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$SB/repo/"
if find "$SB/repo" \( -name credentials.json -o -name token.json \
        -o -name 'client_secret_*.json' -o -name '*.bak-*' \) | grep -q .; then
  echo "REFUSING: personal or backup files in the sandbox copy"; exit 1
fi
PY="$SB/venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv "$SB/venv"
  "$PY" -m pip install --quiet --disable-pip-version-check --no-deps \
      -r "$REPO/tools/bundle-requirements-macos.txt"
fi
PREFS="$SB/repo/local_device_prefs.json"
if [ -f "$PREFS" ]; then
  "$PY" -c "import json,sys; p=json.load(open(sys.argv[1])).get('db_custom_path') or ''; sys.exit(1 if p and not p.startswith(sys.argv[2]) else 0)" "$PREFS" "$SB" \
    || { echo "REFUSING: sandbox prefs point outside the sandbox"; exit 1; }
else
  printf '{"db_custom_path": "%s/data", "setup_done": true}\n' "$SB" > "$PREFS"
fi
[ -f "$SB/data/acm_database.json" ] || cp "$SB/repo/acm_database.json" "$SB/data/"
for v in $(env | grep -o '^ONEDRIVE[^=]*' || true); do unset $v; done
export HOME="$SB/home" CAM_DB_PATH="$SB/data/acm_database.json" \
       CAM2_APP_DATA="$SB/cam2data" CAM2_DOCUMENTS_OVERRIDE="$SB/docs2" \
       CAM_DOCUMENTS_OVERRIDE="$SB/docs" CAM_SANDBOX_URL_LOG="$SB/opened-urls.txt" \
       BROWSER="\"$PY\" \"$SB/repo/tools/browser_check/log_url.py\" %s"
echo "sandbox DB: $CAM_DB_PATH"
cd "$SB/repo"
exec "$PY" -m streamlit run app.py --server.headless true --server.port 8611 \
     --browser.gatherUsageStats false
