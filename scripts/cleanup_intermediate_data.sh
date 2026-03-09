#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

paths=(
  "$base_dir/data/raw/extracted"
  "$base_dir/data/raw/tifs"
  "$base_dir/data/canada/elv/clipped"
)

purge_dir_contents() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    return 0
  fi
  echo "Cleaning $dir"
  find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
}

echo "Removing intermediate data (keeping downloads, COGs, and VRT mosaics)..."
for p in "${paths[@]}"; do
  purge_dir_contents "$p"
done

echo "Done."
