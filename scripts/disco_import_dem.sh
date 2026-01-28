#!/usr/bin/env bash
set -euo pipefail

DISCO="${DISCO:-}"
PROJECT="${PROJECT:-}"
VOLUME="${VOLUME:-dem-data}"
SRC_MOSAIC="${SRC_MOSAIC:-./data/mosaic/canada.vrt}"
SRC_CANADA="${SRC_CANADA:-./data/canada}"

if [[ -z "${DISCO}" || -z "${PROJECT}" ]]; then
  echo "Usage: DISCO=<disco-host> PROJECT=<project> $0"
  echo "Optional: VOLUME=dem-data SRC_MOSAIC=./data/mosaic/canada.vrt SRC_CANADA=./data/canada"
  exit 1
fi

if [[ ! -f "${SRC_MOSAIC}" ]]; then
  echo "Missing file: ${SRC_MOSAIC}"
  exit 1
fi

if [[ ! -d "${SRC_CANADA}" ]]; then
  echo "Missing directory: ${SRC_CANADA}"
  exit 1
fi

stage="$(mktemp -d)"
tarball="$(mktemp /tmp/merit-dem-data.XXXXXX.tgz)"
cleanup() {
  rm -rf "${stage}" "${tarball}"
}
trap cleanup EXIT

mkdir -p "${stage}/mosaic" "${stage}/canada"
cp -R "${SRC_MOSAIC}" "${stage}/mosaic/"
cp -R "${SRC_CANADA}" "${stage}/"

tar -C "${stage}" -czf "${tarball}" .

disco volumes:import \
  --disco "${DISCO}" \
  --project "${PROJECT}" \
  --volume "${VOLUME}" \
  --input "${tarball}"

echo "DEM data imported into volume '${VOLUME}' on ${DISCO} (project: ${PROJECT})."
