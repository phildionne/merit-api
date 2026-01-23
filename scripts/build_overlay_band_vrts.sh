#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="$ROOT_DIR/data/overlays"
MOSAIC_VRT="$OVERLAY_DIR/mosaic_elvhypsometric.vrt"

shopt -s nullglob
inputs=("$OVERLAY_DIR"/*_elvhypsometric.tif)
shopt -u nullglob

if [[ ${#inputs[@]} -eq 0 ]]; then
  echo "No overlay TIFFs found in $OVERLAY_DIR"
  exit 1
fi

if [[ ! -f "$MOSAIC_VRT" || $(find "$OVERLAY_DIR" -maxdepth 1 -name "*_elvhypsometric.tif" -newer "$MOSAIC_VRT" | wc -l) -gt 0 ]]; then
  echo "Building mosaic VRT: $MOSAIC_VRT"
  gdalbuildvrt -q "$MOSAIC_VRT" "${inputs[@]}"
else
  echo "Up to date: $MOSAIC_VRT"
fi

for input in "${inputs[@]}"; do
  base="$(basename "$input" .tif)"
  for band in 1 2 3; do
    case "$band" in
      1) suffix="r" ;;
      2) suffix="g" ;;
      3) suffix="b" ;;
    esac
    output="$OVERLAY_DIR/${base}_${suffix}.vrt"
    if [[ -f "$output" && "$output" -nt "$input" ]]; then
      echo "Up to date: $output"
      continue
    fi
    echo "Building $output"
    gdal_translate -q -of VRT -b "$band" "$input" "$output"
  done
done

for band in 1 2 3; do
  case "$band" in
    1) suffix="r" ;;
    2) suffix="g" ;;
    3) suffix="b" ;;
  esac
  output="$OVERLAY_DIR/mosaic_elvhypsometric_${suffix}.vrt"
  if [[ -f "$output" && "$output" -nt "$MOSAIC_VRT" ]]; then
    echo "Up to date: $output"
    continue
  fi
  echo "Building $output"
  gdal_translate -q -of VRT -b "$band" "$MOSAIC_VRT" "$output"
done

echo "Done. Band VRTs written to $OVERLAY_DIR"
