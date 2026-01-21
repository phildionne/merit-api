#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

src_dir="$base_dir/data/canada/clipped"
out_dir="$base_dir/data/canada/cog"

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
    -co COMPRESS=DEFLATE \
    -co LEVEL=9 \
    -co BLOCKSIZE=512 \
    -co BIGTIFF=IF_SAFER \
    -co OVERVIEWS=AUTO \
    -co RESAMPLING=NEAREST \
    "$in_tif" "$out_tif"

done
