#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_URL="${ARCHIVE_URL:-}"
ARCHIVE_PART_URLS="${ARCHIVE_PART_URLS:-}"
DEST="${DEST:-/data}"
ARCHIVE_PATH="${ARCHIVE_PATH:-/tmp/data.tar.gz}"

if [[ -z "${ARCHIVE_URL}" && -z "${ARCHIVE_PART_URLS}" ]]; then
  echo "ARCHIVE_URL or ARCHIVE_PART_URLS is required." >&2
  exit 1
fi

if [[ -n "${ARCHIVE_URL}" && -n "${ARCHIVE_PART_URLS}" ]]; then
  echo "Set only one of ARCHIVE_URL or ARCHIVE_PART_URLS." >&2
  exit 1
fi

shell_quote() {
  printf "'%s'" "${1//\'/\'\\\'\'}"
}

run_remote_python() {
  local script="$1"
  local encoded_script
  local remote_cmd
  encoded_script="$(printf '%s' "${script}" | base64 | tr -d '\n')"
  remote_cmd="$(
    printf "ARCHIVE_URL=%s ARCHIVE_PART_URLS=%s DEST=%s ARCHIVE_PATH=%s python -c %s" \
      "$(shell_quote "${ARCHIVE_URL}")" \
      "$(shell_quote "${ARCHIVE_PART_URLS}")" \
      "$(shell_quote "${DEST}")" \
      "$(shell_quote "${ARCHIVE_PATH}")" \
      "$(shell_quote "import base64; exec(base64.b64decode(\"${encoded_script}\").decode())")"
  )"
  railway ssh "${remote_cmd}"
}

echo "Checking archive reachability from Railway..."
run_remote_python '
import os
import urllib.request

archive_url = os.environ["ARCHIVE_URL"]
part_urls = os.environ["ARCHIVE_PART_URLS"].split()

urls = [archive_url] if archive_url else part_urls
for index, url in enumerate(urls, start=1):
    with urllib.request.urlopen(url) as response:
        response.read(1)
    print(f"Archive source {index}/{len(urls)} is reachable.")
'

echo "Importing archive into ${DEST}..."
run_remote_python '
import os
import pathlib
import shutil
import tarfile
import urllib.request
from urllib.error import URLError

archive_url = os.environ["ARCHIVE_URL"]
part_urls = os.environ["ARCHIVE_PART_URLS"].split()
dest = pathlib.Path(os.environ["DEST"])
archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])

archive_path.parent.mkdir(parents=True, exist_ok=True)
dest.mkdir(parents=True, exist_ok=True)

downloaded_size = 0
urls = [archive_url] if archive_url else part_urls

try:
    with archive_path.open("wb") as fh:
        for index, url in enumerate(urls, start=1):
            expected_size = None
            part_downloaded_size = 0
            print(f"Downloading archive source {index}/{len(urls)}...")
            with urllib.request.urlopen(url) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    expected_size = int(content_length)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    part_downloaded_size += len(chunk)
                    downloaded_size += len(chunk)
            if expected_size is not None and part_downloaded_size != expected_size:
                raise RuntimeError(
                    "Downloaded archive source "
                    f"{index}/{len(urls)} is truncated: got {part_downloaded_size} bytes, "
                    f"expected {expected_size} bytes"
                )
except URLError as exc:
    raise RuntimeError(f"Failed to download archive: {exc}") from exc

top_level_paths = set()

def normalized_members(tar):
    for member in tar.getmembers():
        path = pathlib.PurePosixPath(member.name)
        parts = [part for part in path.parts if part not in ("", ".")]
        if not parts:
            continue
        if parts[0] == "data":
            parts = parts[1:]
        if not parts:
            continue
        if any(part == ".." for part in parts):
            raise RuntimeError(f"Refusing unsafe archive entry: {member.name}")
        top_level_paths.add(parts[0])
        member.name = str(pathlib.PurePosixPath(*parts))
        yield member

try:
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(dest, members=normalized_members(tar), filter="data")
except (EOFError, tarfile.ReadError) as exc:
    raise RuntimeError("Downloaded archive is incomplete or corrupt.") from exc
finally:
    archive_path.unlink(missing_ok=True)

if not top_level_paths:
    raise RuntimeError("Archive did not contain any extractable paths.")

missing_paths = [str(dest / path) for path in sorted(top_level_paths) if not (dest / path).exists()]
if missing_paths:
    raise RuntimeError(
        "Missing extracted paths after import: "
        + ", ".join(missing_paths)
    )

print(
    "Import complete: "
    f"{', '.join(str(dest / path) for path in sorted(top_level_paths))} "
    f"({downloaded_size} bytes)"
)
'

echo "Railway data import finished."
