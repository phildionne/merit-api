#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

download_dir="$base_dir/data/raw/downloads"
urls_file="$base_dir/data/urls.txt"

mkdir -p "$download_dir"

if compgen -G "$download_dir/*" > /dev/null; then
  echo "Archives already present in $download_dir. Skipping download."
  ls -lh "$download_dir"
  exit 0
fi

if [ ! -f "$urls_file" ]; then
  echo "No data/urls.txt found and no archives in $download_dir." >&2
  echo "Create data/urls.txt with one MERIT-Hydro URL per line, or manually place archives into $download_dir." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for downloads." >&2
  exit 1
fi

count=0
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%%#*}"
  line="${line//$'\r'/}"
  if [ -z "$line" ]; then
    continue
  fi

  url="$line"
  filename="$(basename "${url%%\?*}")"
  if [ -z "$filename" ]; then
    echo "Could not determine filename from URL: $url" >&2
    exit 1
  fi
  dest="$download_dir/$filename"

  echo "Downloading $url -> $dest"
  curl -L --fail --retry 3 --continue-at - -o "$dest" "$url"

  if [ ! -s "$dest" ]; then
    echo "Downloaded file is empty: $dest" >&2
    exit 1
  fi

  count=$((count + 1))

done < "$urls_file"

if [ "$count" -eq 0 ]; then
  echo "No URLs found in $urls_file. Add URLs or place archives in $download_dir." >&2
  exit 1
fi

echo "Downloaded $count archives."
ls -lh "$download_dir"
