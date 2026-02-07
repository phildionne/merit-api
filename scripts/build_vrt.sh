#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

merit_var="${MERIT_VAR:-}"
if [[ "$merit_var" != "elv" && "$merit_var" != "wth" ]]; then
  echo "MERIT_VAR must be set to 'elv' or 'wth'" >&2
  echo "Example: MERIT_VAR=elv ./scripts/build_vrt.sh" >&2
  exit 1
fi

cog_dir="$base_dir/data/canada/$merit_var/cog"
output_vrt="$base_dir/data/mosaic/canada_${merit_var}.vrt"

shopt -s nullglob
cogs=("$cog_dir"/*.tif "$cog_dir"/*.tiff)

if [ "${#cogs[@]}" -eq 0 ]; then
  echo "No COGs found in $cog_dir" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_vrt")"

if [ -f "$output_vrt" ]; then
  echo "Skipping existing VRT: $output_vrt"
  exit 0
fi

tmp_list="$(mktemp)"
python3 - <<'PY' "$output_vrt" "${cogs[@]}" > "$tmp_list"
import os
import sys

vrt_path = sys.argv[1]
sources = sys.argv[2:]
base_dir = os.path.dirname(vrt_path)

for src in sources:
    print(os.path.relpath(src, start=base_dir))
PY

echo "Building VRT: $output_vrt"
(cd "$(dirname "$output_vrt")" && gdalbuildvrt -input_file_list "$tmp_list" "$(basename "$output_vrt")")

rm -f "$tmp_list"

gdalinfo "$output_vrt" >/dev/null
echo "VRT built successfully."
