#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

api_url="${API_URL:-http://localhost:8000}"
api_key="${SMOKE_API_KEY:-${API_KEY:-}}"

health_url="$api_url/health"
elev_url="$api_url/elevation?lat=46.8139&lng=-71.2080"
river_width_url="$api_url/width"
river_width_payload='{"points":[{"id":"p1","lat":46.8139,"lng":-71.2080},{"id":"p2","lat":0.0,"lng":0.0}]}'

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for smoke test" >&2
  exit 1
fi

if [ -z "$api_key" ]; then
  echo "Set SMOKE_API_KEY (or API_KEY) for authenticated smoke checks" >&2
  exit 1
fi

echo "Checking /health"
health_resp="$(curl -sf "$health_url")"

echo "Health response: $health_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$health_resp" | jq -e '.ok == true' >/dev/null
else
  echo "$health_resp" | grep -q '"ok"' && echo "$health_resp" | grep -q 'true'
fi

echo "Checking /elevation"
elev_resp="$(curl -sf -H "X-API-Key: $api_key" "$elev_url")"

echo "Elevation response: $elev_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$elev_resp" | jq -e 'has("lat") and has("lng") and has("elevation_m") and has("nodata") and has("dataset") and has("source")' >/dev/null
else
  echo "$elev_resp" | grep -q '"lat"'
  echo "$elev_resp" | grep -q '"lng"'
  echo "$elev_resp" | grep -q '"elevation_m"'
  echo "$elev_resp" | grep -q '"nodata"'
  echo "$elev_resp" | grep -q '"dataset"'
  echo "$elev_resp" | grep -q '"source"'
fi

echo "Checking /width"
river_width_resp="$(curl -sf \
  -H "X-API-Key: $api_key" \
  -H "Content-Type: application/json" \
  -d "$river_width_payload" \
  "$river_width_url")"

echo "River width response: $river_width_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$river_width_resp" | jq -e '
    has("points")
    and (.points | type == "array")
    and (.points | length == 2)
    and (.points[0].id == "p1")
    and (.points[1].id == "p2")
    and (.points[0] | has("lat") and has("lng") and has("wth_raw") and has("nodata"))
  ' >/dev/null
else
  echo "$river_width_resp" | grep -q '"points"'
  echo "$river_width_resp" | grep -q '"id":"p1"'
  echo "$river_width_resp" | grep -q '"id":"p2"'
  echo "$river_width_resp" | grep -q '"wth_raw"'
  echo "$river_width_resp" | grep -q '"nodata"'
fi

echo "Smoke test OK"
