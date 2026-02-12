#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

merit_var="${MERIT_VAR:-}"
if [[ "$merit_var" != "elv" && "$merit_var" != "wth" ]]; then
  echo "MERIT_VAR must be set to 'elv' or 'wth'" >&2
  echo "Example: MERIT_VAR=elv ./scripts/cogify.sh" >&2
  exit 1
fi

src_dir="$base_dir/data/canada/$merit_var/clipped"
out_dir="$base_dir/data/canada/$merit_var/cog"

mkdir -p "$out_dir"

shopt -s nullglob
inputs=("$src_dir"/*.tif "$src_dir"/*.tiff)

if [ "${#inputs[@]}" -eq 0 ]; then
  echo "No clipped GeoTIFFs found in $src_dir" >&2
  exit 1
fi

for in_tif in "${inputs[@]}"; do
  base_name="$(basename "$in_tif")"
  out_tif="$out_dir/$base_name"

  if [ -f "$out_tif" ]; then
    echo "Skipping existing COG: $out_tif"
    continue
  fi

  echo "COGify $in_tif -> $out_tif"
  gdal_translate \
    -of COG \
    -co COMPRESS=ZSTD \
    -co LEVEL=9 \
    -co PREDICTOR=3 \
    -co BLOCKSIZE=512 \
    -co BIGTIFF=IF_SAFER \
    -co OVERVIEWS=NONE \
    "$in_tif" "$out_tif"
done
