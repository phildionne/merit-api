#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

cog_dir="$base_dir/data/canada/elv/cog"
output_vrt="$base_dir/data/mosaic/canada_elv.vrt"
force="${FORCE:-0}"

shopt -s nullglob
cogs=("$cog_dir"/*.tif "$cog_dir"/*.tiff)
shopt -u nullglob

if [ "${#cogs[@]}" -eq 0 ]; then
  echo "No COGs found in $cog_dir" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_vrt")"

needs_rebuild=1
if [ "$force" != "1" ] && [ -f "$output_vrt" ]; then
  newer_count="$(find "$cog_dir" -maxdepth 1 -type f \( -iname "*.tif" -o -iname "*.tiff" \) -newer "$output_vrt" | wc -l | tr -d ' ')"
  if [ "$newer_count" -eq 0 ]; then
    needs_rebuild=0
  fi
fi

if [ "$needs_rebuild" -eq 0 ]; then
  echo "Up to date: $output_vrt"
  exit 0
fi

tmp_list="$(mktemp)"
tmp_vrt="$(mktemp "$(dirname "$output_vrt")/.elv.vrt.tmp.XXXXXX")"
cleanup() {
  rm -f "$tmp_list" "$tmp_vrt"
}
trap cleanup EXIT

python3 - <<'PY' "$output_vrt" "${cogs[@]}" > "$tmp_list"
import os
import sys

vrt_path = sys.argv[1]
sources = sorted(sys.argv[2:])
base_dir = os.path.dirname(vrt_path)

for src in sources:
    print(os.path.relpath(src, start=base_dir))
PY

echo "Building VRT: $output_vrt"
(cd "$(dirname "$output_vrt")" && gdalbuildvrt -input_file_list "$tmp_list" "$(basename "$tmp_vrt")")

gdalinfo "$tmp_vrt" >/dev/null
mv "$tmp_vrt" "$output_vrt"
echo "VRT built successfully."
