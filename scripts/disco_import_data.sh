#!/usr/bin/env bash
set -euo pipefail

DISCO="${DISCO:-}"
PROJECT="${PROJECT:-}"
VOLUME="${VOLUME:-dem-data}"
INCLUDE_VARS="${INCLUDE_VARS:-elv,wth}"

if [[ -z "${DISCO}" || -z "${PROJECT}" ]]; then
  echo "Usage: DISCO=<disco-host> PROJECT=<project> $0"
  echo "Optional: VOLUME=dem-data INCLUDE_VARS=elv,wth"
  exit 1
fi

IFS=',' read -r -a vars <<< "$INCLUDE_VARS"
if [ "${#vars[@]}" -eq 0 ]; then
  echo "INCLUDE_VARS is empty" >&2
  exit 1
fi

stage="$(mktemp -d)"
tarball="$(mktemp /tmp/merit-data.XXXXXX.tgz)"
cleanup() {
  rm -rf "${stage}" "${tarball}"
}
trap cleanup EXIT

mkdir -p "${stage}/mosaic" "${stage}/canada"

for raw_var in "${vars[@]}"; do
  var="$(printf '%s' "$raw_var" | tr -d '[:space:]')"
  if [[ "$var" != "elv" && "$var" != "wth" ]]; then
    echo "Unsupported variable in INCLUDE_VARS: $var" >&2
    exit 1
  fi

  src_mosaic="./data/mosaic/canada_${var}.vrt"
  src_canada="./data/canada/${var}"

  if [[ ! -f "${src_mosaic}" ]]; then
    echo "Missing file: ${src_mosaic}" >&2
    exit 1
  fi

  if [[ ! -d "${src_canada}" ]]; then
    echo "Missing directory: ${src_canada}" >&2
    exit 1
  fi

  cp -R "${src_mosaic}" "${stage}/mosaic/"
  cp -R "${src_canada}" "${stage}/canada/"
done

tar -C "${stage}" -czf "${tarball}" .

disco volumes:import \
  --disco "${DISCO}" \
  --project "${PROJECT}" \
  --volume "${VOLUME}" \
  --input "${tarball}"

echo "Data imported into volume '${VOLUME}' on ${DISCO} (project: ${PROJECT})."
