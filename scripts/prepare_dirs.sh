#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$base_dir/data/raw/downloads"
mkdir -p "$base_dir/data/raw/extracted"
mkdir -p "$base_dir/data/raw/tifs"

for var in elv; do
  mkdir -p "$base_dir/data/canada/$var/clipped"
  mkdir -p "$base_dir/data/canada/$var/cog"

done

mkdir -p "$base_dir/data/mosaic"

echo "Prepared data directories under $base_dir/data"
