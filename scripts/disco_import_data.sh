#!/usr/bin/env bash
set -euo pipefail

DISCO="${DISCO:-}"
PROJECT="${PROJECT:-}"
VOLUME="${VOLUME:-dem-data}"

if [[ -z "${DISCO}" || -z "${PROJECT}" ]]; then
  echo "Usage: DISCO=<disco-host> PROJECT=<project> $0"
  echo "Optional: VOLUME=dem-data"
  exit 1
fi

stage="$(mktemp -d)"
tarball="$(mktemp /tmp/merit-data.XXXXXX.tgz)"
cleanup() {
  rm -rf "${stage}" "${tarball}"
}
trap cleanup EXIT

mkdir -p "${stage}/mosaic" "${stage}/canada"

var="elv"
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

tar -C "${stage}" -czf "${tarball}" .

disco volumes:import \
  --disco "${DISCO}" \
  --project "${PROJECT}" \
  --volume "${VOLUME}" \
  --input "${tarball}"

echo "Data imported into volume '${VOLUME}' on ${DISCO} (project: ${PROJECT})."
