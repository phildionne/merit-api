#!/usr/bin/env bash
set -euo pipefail

required_tools=(gdalinfo gdalwarp gdal_translate gdalbuildvrt curl unzip tar)
missing=()

for tool in "${required_tools[@]}"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing+=("$tool")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing required tools: ${missing[*]}" >&2
  echo "Install GDAL (gdalinfo/gdalwarp/gdal_translate/gdalbuildvrt), curl, unzip, and tar." >&2
  exit 1
fi

echo "Found required tools. Versions:"

gdalinfo --version
curl --version | head -n 1
unzip -v | head -n 1

tar --version | head -n 1
