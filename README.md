# MERIT-Hydro (MERIT DEM) Local Preprocessing + Docker API

This repo provides an end-to-end workflow to **manually download MERIT-Hydro data**, preprocess it locally with GDAL into **COGs + a VRT mosaic**, and run a **Docker-only FastAPI service** to query elevation by latitude/longitude.

**Important:** MERIT-Hydro downloads require a license/registration. This project **does not** bypass that gate. You must manually accept the license and supply your own download URLs or archives.

## What you get

- Local preprocessing pipeline (host machine) using GDAL
- Output datasets:
  - `data/canada/clipped/*.tif` (Canada bbox clips)
  - `data/canada/cog/*.tif` (COG-optimized GeoTIFFs)
  - `data/mosaic/canada.vrt` (VRT mosaic)
- Docker-only API (no GDAL in container)
  - `GET /elevation?lat=<float>&lng=<float>`
  - `POST /elevation` with a batch payload

## Default Canada BBox (EPSG:4326)

Used by the clip script, configurable via env vars:

- `BBOX_MIN_LON=-80.0`
- `BBOX_MIN_LAT=41.0`
- `BBOX_MAX_LON=-55.0`
- `BBOX_MAX_LAT=63.0`

## Quickstart

1. **Install GDAL locally** (host machine)

   - You need `gdalinfo`, `gdalwarp`, `gdal_translate`, `gdalbuildvrt` available in your `PATH`.
   - macOS (Homebrew) example:
     ```bash
     brew install gdal
     which gdalinfo gdalwarp gdal_translate gdalbuildvrt
     gdalinfo --version
     ```

2. **Prepare directories**

   ```bash
   ./scripts/00_check_deps.sh
   ./scripts/10_prepare_dirs.sh
   ```

3. **Manual download step (required)**

   - Register/accept MERIT-Hydro license and obtain download credentials
   - Download this subset of the data (covers the default bbox -80 to -55 lon, 41 to 63 lat):
     - N60–N90: elv_n60w090.tar, elv_n60w060.tar
     - N30–N60: elv_n30w090.tar, elv_n30w060.tar
   - Download the required archives and place them in `data/raw/downloads/`.

4. **Unpack and discover**

   ```bash
   ./scripts/30_unpack_and_discover.sh
   ```

5. **Clip to Canada bbox**

   ```bash
   ./scripts/40_clip_canada.sh
   ```

6. **COGify the clipped tiles**

   ```bash
   ./scripts/50_cogify.sh
   ```

7. **Build VRT mosaic**

   ```bash
   ./scripts/60_build_vrt.sh
   ```

8. **Run the API**

   ```bash
   docker compose up --build
   ```

   and run `curl "http://localhost:8000/elevation?lat=46.8139&lng=-71.2080"`

## Script-by-script details

### `scripts/00_check_deps.sh`

Validates required tools and prints versions. Fails fast if missing tools.

### `scripts/10_prepare_dirs.sh`

Creates the full data directory layout under `data/` and writes `data/urls.txt.example` if missing.

### `scripts/20_download_merit_hydro.sh`

Supports two workflows:

- If archives exist in `data/raw/downloads`, it **skips downloading**.
- Otherwise, it reads `data/urls.txt` and downloads each URL with `curl -L --fail --retry 3 --continue-at -`.

### `scripts/30_unpack_and_discover.sh`

- Unpacks `*.zip` and `*.tar.gz`/`*.tgz` into `data/raw/extracted/`.
- Finds all `.tif`/`.tiff` and symlinks them into `data/raw/tifs/`.
- Prints a summary (count + `gdalinfo` lines for up to 5 rasters).
- Idempotent: if `data/raw/extracted/` already has contents, it **skips extraction** unless `FORCE=1`.

### `scripts/40_clip_canada.sh`

- Clips each input raster to the Canada bbox using `gdalwarp`.
- Reprojects to EPSG:4326 if needed.
- Uses nearest-neighbor resampling to preserve the source resolution.
- Sets a consistent `-dstnodata` (reads from source, or uses `-9999` if missing).
- Deletes fully nodata outputs (empty clips).
- Skips if output is newer than input.

### `scripts/50_cogify.sh`

- Converts each clipped raster into a Cloud-Optimized GeoTIFF (COG) using `gdal_translate -of COG`.
- Uses:
  - `COMPRESS=DEFLATE` with `LEVEL=9`
  - `BLOCKSIZE=512`
  - `OVERVIEWS=AUTO` with nearest resampling
- Skips if output is newer than input.

### `scripts/60_build_vrt.sh`

- Builds `data/mosaic/canada.vrt` from all COGs using `gdalbuildvrt`.
- Fails if no COGs exist.
- Validates the VRT with `gdalinfo`.

### `scripts/70_smoke_test.sh`

- Requires the Docker API to be running.
- Calls `/health` and `/elevation` for Québec City.
- Validates JSON keys (uses `jq` if available, otherwise `grep`).

## API behavior

- **GET `/health`** returns `{ "ok": true }`.
- **GET `/elevation?lat=&lng=`**:
  - If out of bounds: returns HTTP 400.
  - If nodata: returns `elevation_m: null` and `nodata: true`.
- **POST `/elevation`**:
  - Accepts `{ "points": [ {"lat":..,"lng":..}, ... ] }`.
  - Returns `{ "points": [ ... ] }` with per-point results.
  - If a point is out of bounds, the response includes `"error": "out_of_bounds"` for that point.

Sampling uses **nearest-neighbor** (no bilinear smoothing) for stability and speed.

## Terracotta usage (optional visualization)

Terracotta serves tiles from the COGs for quick visualization. It does **not** replace the FastAPI elevation API.

### Quick serve (no DB)

```bash
docker compose up --build terracotta
```

### List datasets

```bash
curl http://127.0.0.1:8080/datasets
```

Example response:

```json
{ "datasets": [{ "tile": "n40w060" }], "limit": 100, "page": 0 }
```

### Tile URL template

Once you know a dataset key (e.g. `n40w060`), the tile URL is:

```
http://127.0.0.1:8080/singleband/n40w060/{z}/{x}/{y}.png
```

## Viewer (Leaflet)

The repo includes `viewer/index.html`, a simple Leaflet viewer with:

- A basemap for context
- The Terracotta elevation tile layer
- A live elevation readout that calls the FastAPI `/elevation` endpoint

### Run it

1. Start FastAPI on port 8000: `docker compose up --build`
2. Start Terracotta on port 8080
3. Serve the `viewer/` folder:

```bash
python3 -m http.server 63783 -d viewer
```

Open: `http://localhost:63783/`

If you change the Terracotta port or dataset key, edit `viewer/index.html`.

## Troubleshooting

### GDAL / PROJ issues

- If `gdalinfo` or `gdalwarp` fail with projection errors, ensure GDAL is installed with PROJ data and environment variables are set properly for your system.

### Nodata / empty clips

- If a clipped raster is fully nodata, it is deleted automatically. This can happen if your bbox does not intersect a tile.

### VRT references missing files

- The VRT references the COG file paths at build time. If you move or delete COGs, or the API runs in Docker with `/data` mounted, rebuild the VRT using:
  ```bash
  ./scripts/60_build_vrt.sh
  ```

## Data size & storage

MERIT-Hydro tiles can be large. The workflow stores:

- Raw downloads
- Extracted data
- Clipped tiles
- COGs

After you validate your VRT and API, you can consider deleting `data/raw/extracted` and `data/canada/clipped` to save space, keeping only:

- `data/canada/cog/`
- `data/mosaic/canada.vrt`

## Next steps

- Build a tile index to route queries to a single COG instead of a VRT for faster I/O.
- Swap MERIT-Hydro for higher-resolution HRDEM tiles where available.
