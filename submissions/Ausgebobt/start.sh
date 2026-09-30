#!/usr/bin/env bash
# ALIBI starten: richtet bei Bedarf Python-Umgebung und Oberfläche ein und startet alles auf einer Adresse.
#   ./start.sh          normaler Start (empfohlen)
#   ./start.sh --dev    Entwicklungsmodus (Vite-Hot-Reload auf :5173 + Backend)
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
PORT="${ALIBI_PORT:-8765}"
VENV="$HERE/.venv.nosync"           # *.nosync: wird von iCloud nicht synchronisiert

say() { printf "\033[1;36m[ALIBI]\033[0m %s\n" "$*"; }

PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "Python 3.10+ fehlt. Bitte installieren (python.org oder 'brew install python')."; exit 1; }
if [ ! -x "$VENV/bin/python" ]; then
  say "Richte Python-Umgebung ein (einmalig) …"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r backend/requirements.txt
fi

if [ ! -f frontend/dist/index.html ] || [ "${1:-}" = "--rebuild" ]; then
  command -v npm >/dev/null || { echo "Node.js/npm fehlt für den ersten Oberflächen-Build (https://nodejs.org)."; exit 1; }
  say "Baue Oberfläche (einmalig) …"
  ( cd frontend
    [ -d node_modules.nosync ] || mkdir node_modules.nosync
    [ -e node_modules ] || ln -s node_modules.nosync node_modules
    npm install --no-audit --no-fund --silent
    npm run build --silent )
fi

if command -v bob >/dev/null; then say "Bob Shell gefunden: $(bob --version 2>/dev/null | head -1)"; else say "WARNUNG: Bob Shell nicht gefunden – nur Vorschau möglich."; fi

cd backend
if [ "${1:-}" = "--dev" ]; then
  "$VENV/bin/python" -m uvicorn alibi.api:app --host 127.0.0.1 --port "$PORT" --reload &
  trap 'kill %1' EXIT
  say "Entwicklungsmodus: http://localhost:5173"
  ( cd ../frontend && npm run dev )
else
  echo
  say "────────────────────────────────────────────"
  say "  ALIBI läuft:  http://localhost:$PORT"
  say "  Beenden mit Ctrl+C"
  say "────────────────────────────────────────────"
  echo
  [ -z "${ALIBI_NO_OPEN:-}" ] && ( sleep 2; command -v open >/dev/null && open "http://localhost:$PORT" ) >/dev/null 2>&1 &
  exec "$VENV/bin/python" -m uvicorn alibi.api:app --host 127.0.0.1 --port "$PORT"
fi
