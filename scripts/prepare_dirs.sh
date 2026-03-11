#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$base_dir/data/raw/downloads"
mkdir -p "$base_dir/data/raw/extracted"
mkdir -p "$base_dir/data/raw/tifs"
mkdir -p "$base_dir/data/canada/elv/clipped"
mkdir -p "$base_dir/data/canada/elv/cog"

mkdir -p "$base_dir/data/mosaic"

echo "Prepared data directories under $base_dir/data"
