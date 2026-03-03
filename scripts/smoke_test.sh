#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

api_url="${API_URL:-http://localhost:8000}"
api_key="${SMOKE_API_KEY:-${API_KEY:-}}"

health_url="$api_url/health"
ready_url="$api_url/ready"
elev_url="$api_url/elevation?lat=46.8139&lng=-71.2080"

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

echo "Checking /ready"
ready_resp="$(curl -sf "$ready_url")"

echo "Ready response: $ready_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$ready_resp" | jq -e 'has("ok") and has("dem_ready")' >/dev/null
else
  echo "$ready_resp" | grep -q '"ok"'
  echo "$ready_resp" | grep -q '"dem_ready"'
fi

echo "Checking /elevation"
elev_resp="$(curl -sf -H "X-API-Key: $api_key" "$elev_url")"

echo "Elevation response: $elev_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$elev_resp" | jq -e '
    has("version") and
    has("source") and
    has("line_length_m") and
    has("points") and
    has("quality") and
    (.points | type == "array") and
    (.points | length > 0) and
    (.points[0] | has("chainage_m") and has("elevation_m") and has("status"))
  ' >/dev/null
else
  echo "$elev_resp" | grep -q '"version"'
  echo "$elev_resp" | grep -q '"source"'
  echo "$elev_resp" | grep -q '"line_length_m"'
  echo "$elev_resp" | grep -q '"points"'
  echo "$elev_resp" | grep -q '"quality"'
fi

echo "Smoke test OK"
