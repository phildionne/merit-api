# MERIT-API

This repo provides an end-to-end workflow to **manually download MERIT-Hydro data**, preprocess it locally with GDAL into **COGs + VRT mosaics**, and run a **Docker-only FastAPI service** to query elevation and river width by latitude/longitude.

**Important:** MERIT-Hydro downloads require a license/registration. This project **does not** bypass that gate. You must manually accept the license and supply your own download URLs or archives.

## What you get

- Local preprocessing pipeline using GDAL
- Output datasets (default bbox):
  - `data/canada/elv/cog/*.tif` (elevation COGs)
  - `data/canada/wth/cog/*.tif` (width COGs)
  - `data/mosaic/canada_elv.vrt` (elevation VRT mosaic)
  - `data/mosaic/canada_wth.vrt` (width VRT mosaic)
- API
  - `GET /elevation?lat=<float>&lng=<float>`
  - `POST /elevation` with a batch payload
  - `POST /width` with an ID-based batch payload

## Default BBox (EPSG:4326)

This BBbox is used by the clip script to reduce file size; configurable via env vars:

- `BBOX_MIN_LON=-80.0`
- `BBOX_MIN_LAT=41.0`
- `BBOX_MAX_LON=-55.0`
- `BBOX_MAX_LAT=63.0`

## Quickstart

### 1. Install GDAL locally

You need `gdalinfo`, `gdalwarp`, `gdal_translate`, `gdalbuildvrt` available in your `PATH`.

```bash
brew install gdal
```

### 2. Prepare directories

- Validates required tools and prints versions. Fails fast if missing tools.
- Creates the full data directory layout under `data/`
- Creates variable URL templates:
  - `data/raw/urls.elv.txt.example`
  - `data/raw/urls.wth.txt.example`

```bash
./scripts/check_deps.sh
./scripts/prepare_dirs.sh
```

### 3. Migrate existing local elevation data (one-time)

If you already have a working elevation dataset in legacy paths (`data/canada/cog`, `data/mosaic/canada.vrt`), migrate it without re-downloading or reprocessing:

```bash
./scripts/migrate_data_layout.sh
```

This only moves files and rewrites VRT source paths; it does not run clip/COG/VRT generation.

### 4. Manual download step

- Register/accept MERIT-Hydro license and obtain download credentials
- Download MERIT archives into `data/raw/downloads/`.
- Elevation examples (covers the default bbox -80 to -55 lon, 41 to 63 lat):
  - N60–N90: `elv_n60w090.tar`, `elv_n60w060.tar`
  - N30–N60: `elv_n30w090.tar`, `elv_n30w060.tar`
- Width archives should follow the same MERIT naming convention with `_wth`.

### 5. Unpack and discover

- Unpacks archives into shared `data/raw/extracted/`.
- Finds `.tif`/`.tiff` and symlinks them into shared `data/raw/tifs/`.
- Applies a filename-based bbox prefilter so obvious non-intersecting tiles are not linked for downstream steps.

```bash
./scripts/unpack_and_discover.sh
```

### 6. Clip to bbox by variable

- Clips each input raster to the configured bbox
- Reprojects to EPSG:4326 if needed
- Deletes fully nodata outputs (empty clips)

```bash
MERIT_VAR=elv ./scripts/clip_canada.sh
MERIT_VAR=wth ./scripts/clip_canada.sh
```

### 7. COGify the clipped tiles by variable

- Converts each clipped raster into a Cloud-Optimized GeoTIFF (COG)
- Skips if output is newer than input
- COGs use moderate lossless compression (`COMPRESS=ZSTD`, `LEVEL=9`, `PREDICTOR=3`) and disable overviews (`OVERVIEWS=NONE`) to reduce storage usage

```bash
MERIT_VAR=elv ./scripts/cogify.sh
MERIT_VAR=wth ./scripts/cogify.sh
```

### 8. Build VRT mosaics by variable

Builds variable-specific mosaics from COGs using `gdalbuildvrt`:

```bash
MERIT_VAR=elv ./scripts/build_vrt.sh
MERIT_VAR=wth ./scripts/build_vrt.sh
```

### 9. Run the API

This exposes both the API and a terracota tile server:

```bash
docker compose up --build
```

- **GET `/health`** returns `{ "ok": true }`.
- **GET `/elevation?lat=&lng=`**:
  - If out of bounds: returns HTTP 400.
  - If nodata: returns `elevation_m: null` and `nodata: true`.
- **POST `/elevation`**:
  - Accepts `{ "points": [ {"lat":..,"lng":..}, ... ] }`.
  - Returns `{ "points": [ ... ] }` with per-point results.
  - If a point is out of bounds, the response includes `"error": "out_of_bounds"` for that point.
- **POST `/width`**:
  - Accepts `{ "points": [ {"id":"p1","lat":..,"lng":..}, ... ] }`.
  - Returns `{ "points": [ ... ] }` with one result per input point in the same order.
  - Each result includes `id`, `lat`, `lng`, `wth_raw`, and `nodata`.
  - If a point is out of bounds, the response includes `"error": "out_of_bounds"` for that point.
  - `wth_raw` semantics:
    - `> 0`: centerline river width in meters
    - `-1`: non-centerline water pixel
    - `0`: non-water pixel
    - `-9999`: undefined/ocean nodata

Sampling uses **nearest-neighbor** (no bilinear smoothing) for stability and speed.

### curl examples

```bash
# Elevation (single point)
curl -H "X-API-Key: dev-local-key" \
  "http://localhost:8000/elevation?lat=46.8139&lng=-71.2080"

# Width (batch with IDs)
curl -H "X-API-Key: dev-local-key" \
  -H "Content-Type: application/json" \
  -d '{"points":[{"id":"p1","lat":46.8139,"lng":-71.2080},{"id":"p2","lat":46.90,"lng":-71.10}]}' \
  "http://localhost:8000/width"
```

## Authentication

All data endpoints require an API key via the `X-API-Key` header. The server will fail to start if `API_KEY` is not set.

Example:

```bash
curl -H "X-API-Key: dev-local-key" \
  "http://localhost:8000/elevation?lat=46.8139&lng=-71.2080"
```

## Production configuration (API)

Required environment variables:

- `API_KEY` (required): shared secret for `X-API-Key`
- `DEM_PATH` (required): path to the elevation VRT mosaic (default `/data/mosaic/canada_elv.vrt`)
- `WTH_PATH` (required for `/width`): path to the width VRT mosaic (default `/data/mosaic/canada_wth.vrt`)

Optional:

- `ALLOWED_ORIGINS` (default `*`): comma-separated list of origins for CORS
- `MAX_BATCH` (default `1000`): max points in a batch request
- `WEB_CONCURRENCY` (default `2`): gunicorn worker count
- `LOG_LEVEL` (default `info`)

## Production deployment (Local)

1. Build the image:

```bash
docker build -f Dockerfile.api -t merit-api .
```

2. Run the container (mount the data folder read-only):

```bash
docker run --rm -p 8000:8000 \
  -e API_KEY="your-secret-key" \
  -e DEM_PATH="/data/mosaic/canada_elv.vrt" \
  -e WTH_PATH="/data/mosaic/canada_wth.vrt" \
  -e ALLOWED_ORIGINS="https://your-domain.com" \
  -e WEB_CONCURRENCY="2" \
  -v "$(pwd)/data:/data:ro" \
  merit-api
```

3. Verify:

```bash
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/elevation?lat=46.8139&lng=-71.2080"

curl -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"points":[{"id":"p1","lat":46.8139,"lng":-71.2080}]}' \
  "http://localhost:8000/width"
```

## Production deployment (Disco)

Disco reads `disco.json` at the repo root and builds the API using `Dockerfile.api`.

### One-time MERIT data import

Disco volumes are created on first deploy based on `disco.json`. After the first deploy, import only the needed MERIT variable files.

1. Deploy once to create the volume:

```bash
disco deploy --project <your-project> --disco <your-disco>
```

2. Import selected variable datasets into the `dem-data` volume:

```bash
DISCO=<your-disco> PROJECT=<your-project> INCLUDE_VARS=elv,wth \
  ./scripts/disco_import_data.sh
```

### Required env vars

Set these in your Disco project environment:

- `API_KEY` (required)
- `DEM_PATH=/data/mosaic/canada_elv.vrt`
- `WTH_PATH=/data/mosaic/canada_wth.vrt` (required for `/width`)

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

## Viewer

The repo includes `viewer/index.html`, a simple static viewer with:

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

## Hypsometric overlay workflow (pre-colored)

This repo can generate a pre-colored elevation overlay (0–1000m ramp) and serve it via Terracotta, with a Leaflet opacity slider in the viewer.

The viewer requests the overlay via the mosaic dataset:

```
http://127.0.0.1:8080/rgb/mosaic/elvhypsometric/{z}/{x}/{y}.png?r=r&g=g&b=b
```

### 1. Generate overlays (pre-colored COGs)

```bash
./scripts/make_hypsometric_overlay.sh
```

This writes files like:

- `data/overlays/n40w060_elvhypsometric.tif`

### 2. Build band VRTs for RGB serving

Terracotta's `/rgb` endpoint expects **three datasets** (r/g/b). We create lightweight VRTs that expose the overlay's R, G, B bands as separate datasets, both per-tile and as a mosaic dataset.

```bash
./scripts/build_overlay_band_vrts.sh
```

Outputs (examples):

- Per-tile: `data/overlays/n40w060_elvhypsometric_r.vrt`, `..._g.vrt`, `..._b.vrt`
- Mosaic: `data/overlays/mosaic_elvhypsometric_r.vrt`, `..._g.vrt`, `..._b.vrt`

### 3. Serve overlays with Terracotta

Terracotta is configured to serve the per-tile and mosaic band VRTs:

```bash
docker compose up --build terracotta
```

### Notes

- Terracotta key values **cannot contain underscores**, so the overlay layer key is `elvhypsometric` (not `elv_hypsometric`).
- If you change the overlay name or ramp, regenerate the overlays and rebuild the mosaic VRTs.

## Troubleshooting

### GDAL / PROJ issues

- If `gdalinfo` or `gdalwarp` fail with projection errors, ensure GDAL is installed with PROJ data and environment variables are set properly for your system.

### Nodata / empty clips

If a clipped raster is fully nodata, it is deleted automatically. This can happen if your bbox does not intersect a tile.

### VRT references missing files

The VRT references the COG file paths at build time. If you move or delete COGs, or the API runs in Docker with `/data` mounted, rebuild the VRT using:

```bash
MERIT_VAR=elv ./scripts/build_vrt.sh
```

## Data size & storage

MERIT-Hydro tiles can be large. The workflow stores:

- Raw downloads
- Extracted data
- Clipped tiles
- COGs

After you validate your VRTs and API, you can consider deleting intermediate clips to save space, keeping only:

- `data/canada/elv/cog/`
- `data/canada/wth/cog/`
- `data/mosaic/canada_elv.vrt`
- `data/mosaic/canada_wth.vrt`

Use this helper to remove intermediate files in one step:

```bash
./scripts/cleanup_intermediate_data.sh
```

It removes:

- `data/raw/extracted/*`
- `data/raw/tifs/*`
- `data/canada/elv/clipped/*`
- `data/canada/wth/clipped/*`

## Next steps

- Build a tile index to route queries to a single COG instead of a VRT for faster I/O.
- Swap MERIT-Hydro for higher-resolution HRDEM tiles where available.
