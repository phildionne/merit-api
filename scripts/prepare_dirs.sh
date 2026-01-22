#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$base_dir/data/raw/downloads"
mkdir -p "$base_dir/data/raw/extracted"
mkdir -p "$base_dir/data/raw/tifs"
mkdir -p "$base_dir/data/canada/clipped"
mkdir -p "$base_dir/data/canada/cog"
mkdir -p "$base_dir/data/mosaic"

if [ ! -f "$base_dir/data/urls.txt.example" ]; then
  cat <<'EOT' > "$base_dir/data/urls.txt.example"
# MERIT-Hydro download URLs (manual licensing required).
# Add one URL per line after you have accepted the MERIT-Hydro license.
# Example:
# https://example.com/merit/your-download-url.zip
EOT
fi

echo "Prepared data directories under $base_dir/data"
