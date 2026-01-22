#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "$0")/.." && pwd)"

src_dir="$base_dir/data/raw/tifs"
out_dir="$base_dir/data/canada/clipped"

bbox_min_lon="${BBOX_MIN_LON:--80.0}"
bbox_min_lat="${BBOX_MIN_LAT:-41.0}"
bbox_max_lon="${BBOX_MAX_LON:--55.0}"
bbox_max_lat="${BBOX_MAX_LAT:-63.0}"

parallel="${PARALLEL:-4}"

cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)"
warp_threads="ALL_CPUS"
if [ "$parallel" -gt 1 ]; then
  warp_threads=$((cpu_count / parallel))
  if [ "$warp_threads" -lt 1 ]; then
    warp_threads=1
  fi
fi

mkdir -p "$out_dir"

count_inputs="$(find -L "$src_dir" -type f \( -iname "*.tif" -o -iname "*.tiff" \) | wc -l | tr -d ' ')"
if [ "$count_inputs" -eq 0 ]; then
  echo "No input GeoTIFFs found in $src_dir" >&2
  exit 1
fi

process_one() {
  in_tif="$1"
  base_name="$(basename "$in_tif")"
  out_tif="$out_dir/$base_name"

  if [ -f "$out_tif" ]; then
    echo "Skipping existing output: $out_tif"
    return 0
  fi

  info="$(gdalinfo "$in_tif")"

  nodata_val="$(printf '%s\n' "$info" | awk -F'=' '/NoData Value=/{print $2; exit}')"
  if [ -z "$nodata_val" ]; then
    nodata_val="-9999"
  fi

  # Fast filename-based skip: MERIT tiles use n/s + lat, e/w + lon in degrees.
  if [[ "$base_name" =~ ^([ns])([0-9]+)([ew])([0-9]+)_ ]]; then
    lat_sign="${BASH_REMATCH[1]}"
    lat_deg="${BASH_REMATCH[2]}"
    lon_sign="${BASH_REMATCH[3]}"
    lon_deg="${BASH_REMATCH[4]}"

    lat0=$((10#${lat_deg}))
    lon0=$((10#${lon_deg}))

    if [ "$lat_sign" = "s" ]; then
      lat0=$(( -lat0 ))
    fi
    if [ "$lon_sign" = "w" ]; then
      lon0=$(( -lon0 ))
    fi

    # Tiles are 5x5 degrees for MERIT. Compute tile bounds.
    lat_min="$lat0"
    lat_max=$((lat0 + 5))
    lon_min="$lon0"
    lon_max=$((lon0 + 5))

    if ! awk -v minx="$bbox_min_lon" -v miny="$bbox_min_lat" -v maxx="$bbox_max_lon" -v maxy="$bbox_max_lat" \
      -v tminx="$lon_min" -v tminy="$lat_min" -v tmaxx="$lon_max" -v tmaxy="$lat_max" \
      'BEGIN{ if (maxx < tminx || minx > tmaxx || maxy < tminy || miny > tmaxy) exit 1; else exit 0 }'; then
      echo "Skipping tile outside bbox (filename-based): $in_tif"
      return 0
    fi
  fi

  if printf '%s\n' "$info" | grep -q 'EPSG","4326' || printf '%s\n' "$info" | grep -q 'EPSG,4326' || printf '%s\n' "$info" | grep -q 'EPSG:4326'; then
    ul_line="$(printf '%s\n' "$info" | awk '/Upper Left/ {print; exit}')"
    lr_line="$(printf '%s\n' "$info" | awk '/Lower Right/ {print; exit}')"
    ul_lon="$(echo "$ul_line" | awk -F'[(),]' '{print $2}' | xargs)"
    ul_lat="$(echo "$ul_line" | awk -F'[(),]' '{print $3}' | xargs)"
    lr_lon="$(echo "$lr_line" | awk -F'[(),]' '{print $2}' | xargs)"
    lr_lat="$(echo "$lr_line" | awk -F'[(),]' '{print $3}' | xargs)"

    if [ -n "$ul_lon" ] && [ -n "$ul_lat" ] && [ -n "$lr_lon" ] && [ -n "$lr_lat" ]; then
      if awk -v minx="$bbox_min_lon" -v miny="$bbox_min_lat" -v maxx="$bbox_max_lon" -v maxy="$bbox_max_lat" \
        -v ulx="$ul_lon" -v uly="$ul_lat" -v lrx="$lr_lon" -v lry="$lr_lat" \
        'BEGIN{ if (maxx < ulx || minx > lrx || maxy < lry || miny > uly) exit 1; else exit 0 }'; then
        echo "Clipping (EPSG:4326 fast path) $in_tif -> $out_tif"
        gdal_translate \
          -projwin "$bbox_min_lon" "$bbox_max_lat" "$bbox_max_lon" "$bbox_min_lat" \
          -a_nodata "$nodata_val" \
          "$in_tif" "$out_tif"
      else
        echo "Skipping non-intersecting tile: $in_tif"
        return 0
      fi
    else
      echo "Could not parse bounds, falling back to gdalwarp: $in_tif"
      gdalwarp \
        -te "$bbox_min_lon" "$bbox_min_lat" "$bbox_max_lon" "$bbox_max_lat" \
        -t_srs EPSG:4326 \
        -r near \
        -dstnodata "$nodata_val" \
        -multi -wo NUM_THREADS="$warp_threads" \
        "$in_tif" "$out_tif"
    fi
  else
    echo "Clipping (reproject) $in_tif -> $out_tif"
    gdalwarp \
      -te "$bbox_min_lon" "$bbox_min_lat" "$bbox_max_lon" "$bbox_max_lat" \
      -t_srs EPSG:4326 \
      -r near \
      -dstnodata "$nodata_val" \
      -multi -wo NUM_THREADS="$warp_threads" \
      "$in_tif" "$out_tif"
  fi

  valid_percent="$(gdalinfo -stats "$out_tif" | awk -F'=' '/STATISTICS_VALID_PERCENT/{print $2; exit}')"
  if [ -n "$valid_percent" ]; then
    if awk -v vp="$valid_percent" 'BEGIN{ if ((vp + 0) == 0) exit 0; else exit 1 }'; then
      echo "Clipped raster is empty (all nodata). Removing $out_tif"
      rm -f "$out_tif"
      rm -f "$out_tif.aux.xml"
      return 0
    fi
  fi

  return 0
}

export -f process_one
export out_dir bbox_min_lon bbox_min_lat bbox_max_lon bbox_max_lat

find -L "$src_dir" -type f \( -iname "*.tif" -o -iname "*.tiff" \) -print0 | \
  xargs -0 -n 1 -P "$parallel" -I {} bash -c 'process_one "$@"' _ {}
