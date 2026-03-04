#!/usr/bin/env bash
set -euo pipefail

DISCO="${DISCO:-}"
PROJECT="${PROJECT:-}"
VOLUME="${VOLUME:-}"

if [[ -z "${DISCO}" || -z "${PROJECT}" || -z "${VOLUME}" ]]; then
  echo "Usage: DISCO=<disco-host> PROJECT=<project> VOLUME=<volume-id> $0"
  exit 1
fi

set +e
preflight_output="$(disco volumes:list --disco "${DISCO}" --project "${PROJECT}" 2>&1)"
preflight_status=$?
set -e

if [[ ${preflight_status} -ne 0 ]]; then
  echo "Preflight failed: unable to list volumes for project '${PROJECT}' on '${DISCO}'." >&2
  printf '%s\n' "${preflight_output}" >&2
  exit 1
fi

if ! printf '%s\n' "${preflight_output}" | grep -Fxq "${VOLUME}"; then
  echo "Preflight failed: volume '${VOLUME}' was not found for project '${PROJECT}' on '${DISCO}'." >&2
  echo "disco volumes:list output:" >&2
  printf '%s\n' "${preflight_output}" >&2
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
src_cog_dir="./data/canada/${var}/cog"

if [[ ! -f "${src_mosaic}" ]]; then
  echo "Missing file: ${src_mosaic}" >&2
  exit 1
fi

if [[ ! -d "${src_cog_dir}" ]]; then
  echo "Missing directory: ${src_cog_dir}" >&2
  exit 1
fi

cp -R "${src_mosaic}" "${stage}/mosaic/"
mkdir -p "${stage}/canada/${var}"
cp -R "${src_cog_dir}" "${stage}/canada/${var}/"

tar -C "${stage}" -czf "${tarball}" .

disco volumes:import \
  --disco "${DISCO}" \
  --project "${PROJECT}" \
  --volume "${VOLUME}" \
  --input "${tarball}"

echo "Data imported into volume '${VOLUME}' on ${DISCO} (project: ${PROJECT})."
