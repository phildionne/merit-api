#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$base_dir/data/raw/downloads"
mkdir -p "$base_dir/data/raw/extracted"
mkdir -p "$base_dir/data/raw/tifs"

for var in elv wth; do
  mkdir -p "$base_dir/data/canada/$var/clipped"
  mkdir -p "$base_dir/data/canada/$var/cog"

done

mkdir -p "$base_dir/data/mosaic"

if [ ! -f "$base_dir/data/raw/urls.elv.txt.example" ]; then
  cat <<'EOT' > "$base_dir/data/raw/urls.elv.txt.example"
# MERIT-Hydro elevation download URLs (manual licensing required).
# Add one URL per line after you have accepted the MERIT-Hydro license.
# Example:
# https://example.com/merit/elv/your-download-url.tar
EOT
fi

if [ ! -f "$base_dir/data/raw/urls.wth.txt.example" ]; then
  cat <<'EOT' > "$base_dir/data/raw/urls.wth.txt.example"
# MERIT-Hydro river width download URLs (manual licensing required).
# Add one URL per line after you have accepted the MERIT-Hydro license.
# Example:
# https://example.com/merit/wth/your-download-url.tar
EOT
fi

echo "Prepared data directories under $base_dir/data"
