#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

api_url="${API_URL:-http://localhost:8000}"

health_url="$api_url/health"
elev_url="$api_url/elevation?lat=46.8139&lng=-71.2080"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for smoke test" >&2
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
elev_resp="$(curl -sf "$elev_url")"

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

echo "Smoke test OK"
