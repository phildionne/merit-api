#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

download_dir="$base_dir/data/raw/downloads"
extracted_dir="$base_dir/data/raw/extracted"
raw_tifs_dir="$base_dir/data/raw/tifs"

bbox_min_lon="${BBOX_MIN_LON:--82}"
bbox_min_lat="${BBOX_MIN_LAT:-43}"
bbox_max_lon="${BBOX_MAX_LON:--51}"
bbox_max_lat="${BBOX_MAX_LAT:-63}"

mkdir -p "$extracted_dir" "$raw_tifs_dir"

if [ -d "$extracted_dir" ] && [ "$(ls -A "$extracted_dir" 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "Extraction directory is not empty. Skipping extraction (set FORCE=1 to re-extract)."
else
  echo "Extracting archives from $download_dir to $extracted_dir"
  rm -rf "$extracted_dir"/*
  shopt -s nullglob
  archives=("$download_dir"/*)
  if [ "${#archives[@]}" -eq 0 ]; then
    echo "No archives found in $download_dir" >&2
    exit 1
  fi

  for f in "${archives[@]}"; do
    case "$f" in
      *.zip)
        unzip -q "$f" -d "$extracted_dir"
        ;;
      *.tar.gz|*.tgz)
        tar -xzf "$f" -C "$extracted_dir"
        ;;
      *.tar)
        tar -xf "$f" -C "$extracted_dir"
        ;;
      *)
        echo "Skipping unknown archive format: $f" >&2
        ;;
    esac
  done
fi

shopt -s nullglob
all_tifs=()
while IFS= read -r -d '' f; do
  all_tifs+=("$f")
done < <(find "$extracted_dir" -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0)

if [ "${#all_tifs[@]}" -eq 0 ]; then
  echo "No GeoTIFFs found in $extracted_dir" >&2
  exit 1
fi

bbox_intersects_from_filename() {
  local base_name="$1"
  local lower lat_sign lat_deg lon_sign lon_deg lat0 lon0 lat_min lat_max lon_min lon_max
  lower="$(printf '%s' "$base_name" | tr '[:upper:]' '[:lower:]')"

  if [[ ! "$lower" =~ ^([ns])([0-9]+)([ew])([0-9]+)_ ]]; then
    return 0
  fi

  lat_sign="${BASH_REMATCH[1]}"
  lat_deg="${BASH_REMATCH[2]}"
  lon_sign="${BASH_REMATCH[3]}"
  lon_deg="${BASH_REMATCH[4]}"

  lat0=$((10#${lat_deg}))
  lon0=$((10#${lon_deg}))

  if [ "$lat_sign" = "s" ]; then
    lat0=$((-lat0))
  fi
  if [ "$lon_sign" = "w" ]; then
    lon0=$((-lon0))
  fi

  lat_min="$lat0"
  lat_max=$((lat0 + 5))
  lon_min="$lon0"
  lon_max=$((lon0 + 5))

  awk -v minx="$bbox_min_lon" -v miny="$bbox_min_lat" -v maxx="$bbox_max_lon" -v maxy="$bbox_max_lat" \
    -v tminx="$lon_min" -v tminy="$lat_min" -v tmaxx="$lon_max" -v tmaxy="$lat_max" \
    'BEGIN{ if (maxx < tminx || minx > tmaxx || maxy < tminy || miny > tmaxy) exit 1; else exit 0 }'
}

shopt -s nullglob
for existing in "$raw_tifs_dir"/*.tif "$raw_tifs_dir"/*.tiff; do
  rm -f "$existing"
done
shopt -u nullglob

linked=0
skipped_outside_bbox=0
for tif in "${all_tifs[@]}"; do
  base_name="$(basename "$tif")"
  if ! bbox_intersects_from_filename "$base_name"; then
    skipped_outside_bbox=$((skipped_outside_bbox + 1))
    continue
  fi
  ln -sf "$tif" "$raw_tifs_dir/$base_name"
  linked=$((linked + 1))
done

if [ "$linked" -eq 0 ]; then
  echo "No GeoTIFFs intersect the configured bbox in $extracted_dir" >&2
  exit 1
fi

echo "Discovered ${#all_tifs[@]} GeoTIFF(s). Linked $linked intersecting bbox tiles, skipped $skipped_outside_bbox outside bbox."

max=5
shown=0
shopt -s nullglob
for tif in "$raw_tifs_dir"/*.tif "$raw_tifs_dir"/*.tiff; do
  if [ "$shown" -ge "$max" ]; then
    break
  fi
  echo "---"
  echo "File: $tif"
  gdalinfo "$tif" | grep -E "Size is|Pixel Size|Coordinate System is|Corner" || true
  shown=$((shown + 1))
done
shopt -u nullglob
