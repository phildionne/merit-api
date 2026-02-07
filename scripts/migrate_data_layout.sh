#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"
force="${FORCE:-0}"

legacy_clipped="$base_dir/data/canada/clipped"
legacy_cog="$base_dir/data/canada/cog"
legacy_vrt="$base_dir/data/mosaic/canada.vrt"

new_elv_clipped="$base_dir/data/canada/elv/clipped"
new_elv_cog="$base_dir/data/canada/elv/cog"
new_elv_vrt="$base_dir/data/mosaic/canada_elv.vrt"

mkdir -p "$new_elv_clipped" "$new_elv_cog" "$base_dir/data/mosaic"

move_contents() {
  local src="$1"
  local dst="$2"

  if [ ! -d "$src" ]; then
    return 0
  fi

  shopt -s dotglob nullglob
  local items=("$src"/*)
  shopt -u nullglob

  if [ "${#items[@]}" -eq 0 ]; then
    rmdir "$src" 2>/dev/null || true
    return 0
  fi

  for item in "${items[@]}"; do
    local name target
    name="$(basename "$item")"
    target="$dst/$name"

    if [ -e "$target" ] && [ "$force" != "1" ]; then
      echo "Refusing to overwrite existing target: $target" >&2
      echo "Re-run with FORCE=1 to allow overwrite." >&2
      exit 1
    fi

    if [ -e "$target" ] && [ "$force" = "1" ]; then
      rm -rf "$target"
    fi

    mv "$item" "$target"
  done

  rmdir "$src" 2>/dev/null || true
}

rewrite_vrt_paths() {
  local vrt_file="$1"
  python3 - <<'PY' "$vrt_file"
from pathlib import Path
import sys

vrt = Path(sys.argv[1])
text = vrt.read_text(encoding="utf-8")
text = text.replace("../canada/cog/", "../canada/elv/cog/")
text = text.replace("/data/canada/cog/", "/data/canada/elv/cog/")
vrt.write_text(text, encoding="utf-8")
PY
}

echo "Migrating legacy elevation layout to variable layout..."

if [ -d "$legacy_clipped" ]; then
  echo "Moving $legacy_clipped -> $new_elv_clipped"
  move_contents "$legacy_clipped" "$new_elv_clipped"
fi

if [ -d "$legacy_cog" ]; then
  echo "Moving $legacy_cog -> $new_elv_cog"
  move_contents "$legacy_cog" "$new_elv_cog"
fi

if [ -f "$legacy_vrt" ] && [ ! -f "$new_elv_vrt" ]; then
  echo "Creating $new_elv_vrt from legacy VRT"
  cp "$legacy_vrt" "$new_elv_vrt"
  rewrite_vrt_paths "$new_elv_vrt"
elif [ -f "$new_elv_vrt" ]; then
  echo "Found existing $new_elv_vrt; skipping VRT copy"
fi

echo "Migration completed."

echo "Current key paths:"
[ -d "$new_elv_cog" ] && echo "- ELV COG dir: $new_elv_cog"
[ -f "$new_elv_vrt" ] && echo "- ELV VRT: $new_elv_vrt"

echo "No raster regeneration was performed by this script."
