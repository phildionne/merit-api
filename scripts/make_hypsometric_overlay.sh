#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_DIR="$ROOT_DIR/data/canada/cog"
OUTPUT_DIR="$ROOT_DIR/data/overlays"
COLOR_FILE="$OUTPUT_DIR/hypsometric_0_1000.txt"

mkdir -p "$OUTPUT_DIR"

cat >"$COLOR_FILE" <<'EOF'
# Hypsometric tint: 0–1000m, 100m steps, continuous interpolation.
# Format: elevation  R  G  B  [A]
nv 0 0 0 0
0    0   104  55
100  26  152  80
200  102 189  99
300  166 217  106
400  217 239  139
500  254 224  139
600  252 174  97
700  241 130  86
800  217 95   64
900  166 75   45
1000 125 60   35
EOF

shopt -s nullglob
inputs=("$INPUT_DIR"/*.tif)
shopt -u nullglob

if [[ ${#inputs[@]} -eq 0 ]]; then
  echo "No input COGs found in $INPUT_DIR"
  exit 1
fi

for input in "${inputs[@]}"; do
  base="$(basename "$input" .tif)"
  output="$OUTPUT_DIR/${base}hypsometric.tif"
  tmp="$OUTPUT_DIR/.${base}hypsometric.tmp.tif"

  if [[ -f "$output" && "$output" -nt "$input" ]]; then
    echo "Up to date: $output"
    continue
  fi

  echo "Colorizing $input -> $output"
  gdaldem color-relief -alpha "$input" "$COLOR_FILE" "$tmp"
  gdal_translate -of COG \
    -co COMPRESS=DEFLATE \
    -co BIGTIFF=IF_SAFER \
    -co NUM_THREADS=ALL_CPUS \
    "$tmp" "$output"
  rm -f "$tmp"
done

echo "Done. Overlays in $OUTPUT_DIR"
