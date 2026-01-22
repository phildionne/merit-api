#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

download_dir="$base_dir/data/raw/downloads"
extracted_dir="$base_dir/data/raw/extracted"
raw_tifs_dir="$base_dir/data/raw/tifs"

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
tifs=()
while IFS= read -r -d '' f; do
  tifs+=("$f")
done < <(find "$extracted_dir" -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0)

if [ "${#tifs[@]}" -eq 0 ]; then
  echo "No GeoTIFFs found in $extracted_dir" >&2
  exit 1
fi

for tif in "${tifs[@]}"; do
  base_name="$(basename "$tif")"
  ln -sf "$tif" "$raw_tifs_dir/$base_name"
done

count="${#tifs[@]}"
echo "Discovered $count GeoTIFF(s)."

max=5
shown=0
for tif in "${tifs[@]}"; do
  if [ "$shown" -ge "$max" ]; then
    break
  fi
  echo "---"
  echo "File: $tif"
  gdalinfo "$tif" | grep -E "Size is|Pixel Size|Coordinate System is|Corner" || true
  shown=$((shown + 1))
done
