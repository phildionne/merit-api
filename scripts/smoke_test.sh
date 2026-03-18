#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

api_url="${API_URL:-http://localhost:8000}"
api_key="${SMOKE_API_KEY:-${API_KEY:-}}"

health_url="$api_url/health"
ready_url="$api_url/ready"
elev_url="$api_url/elevations"

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
  echo "$ready_resp" | jq -e 'has("ok") and has("status") and (.checks | has("api_key") and has("dem"))' >/dev/null
else
  echo "$ready_resp" | grep -q '"ok"'
  echo "$ready_resp" | grep -q '"checks"'
fi

echo "Checking POST /elevations"
elev_resp="$(
  curl -sf -X POST \
    -H "X-API-Key: $api_key" \
    -H "Content-Type: application/json" \
    "$elev_url" \
    -d '{
      "geojson": {
        "type": "FeatureCollection",
        "features": [
          {
            "type": "Feature",
            "geometry": {
              "type": "LineString",
              "coordinates": [
                [-71.2080, 46.8139],
                [-71.2050, 46.8145]
              ]
            },
            "properties": null
          }
        ]
      },
      "density_m": 200
    }'
)"

echo "Elevation response: $elev_resp"

if command -v jq >/dev/null 2>&1; then
  echo "$elev_resp" | jq -e '
    has("version") and
    has("source") and
    has("line_length_m") and
    has("quality") and
    has("data") and
    (.data.points | type == "array") and
    (.data.start_point | has("chainage_m") and has("elevation_m") and has("status")) and
    (.data.end_point | has("chainage_m") and has("elevation_m") and has("status"))
  ' >/dev/null
else
  echo "$elev_resp" | grep -q '"version"'
  echo "$elev_resp" | grep -q '"source"'
  echo "$elev_resp" | grep -q '"line_length_m"'
  echo "$elev_resp" | grep -q '"quality"'
  echo "$elev_resp" | grep -q '"data"'
fi

echo "Smoke test OK"
