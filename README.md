# MERIT-API

This repo provides an end-to-end workflow to **manually download MERIT-Hydro data**, preprocess it locally with GDAL into **COGs + VRT mosaics**, and run a **Docker-only FastAPI service** to query elevation by latitude/longitude.

**Important:** MERIT-Hydro downloads require a license/registration. This project **does not** bypass that gate. You must manually accept the license and supply your own download URLs or archives.

## What you get

- Local preprocessing pipeline using GDAL
- Output datasets (default bbox):
  - `data/canada/elv/cog/*.tif` (elevation COGs)
  - `data/mosaic/canada_elv.vrt` (elevation VRT mosaic)
- API
  - `POST /elevations` with a batch payload (`points` may contain zero points or many)

## Default BBox (EPSG:4326)

This bbox is used by the clip script to reduce file size; configurable via env vars:

- `BBOX_MIN_LON=-82`
- `BBOX_MIN_LAT=43`
- `BBOX_MAX_LON=-51`
- `BBOX_MAX_LAT=63`

## Quickstart

### 1. Install GDAL locally

You need `gdalinfo`, `gdalwarp`, `gdal_translate`, `gdaldem`, `gdalbuildvrt`, and `python3` available in your `PATH`.

```bash
brew install gdal
```

### 2. Prepare directories

- Validates required tools and prints versions. Fails fast if missing tools.
- Creates the full data directory layout under `data/`
- Creates variable URL templates:
  - `data/raw/urls.elv.txt.example`

```bash
./scripts/check_deps.sh
./scripts/prepare_dirs.sh
```

### 3. Manual download step

- Register/accept MERIT-Hydro license and obtain download credentials
- Download MERIT archives into `data/raw/downloads/`.
- These cover the default BBox:
  - N60–N90: `elv_n60w090.tar`, `elv_n60w060.tar`
  - N30–N60: `elv_n30w090.tar`, `elv_n30w060.tar`

### 4. Unpack and discover

- Unpacks archives into shared `data/raw/extracted/`.
- Finds `.tif`/`.tiff` and symlinks them into shared `data/raw/tifs/`.
- Applies a filename-based bbox prefilter so obvious non-intersecting tiles are not linked for downstream steps.

```bash
./scripts/unpack_and_discover.sh
```

### 5. Clip to bbox

- Clips each input raster to the configured bbox
- Reprojects to EPSG:4326 if needed
- Deletes fully nodata outputs (empty clips)

```bash
./scripts/clip_quebec.sh
```

### 6. COGify the clipped tiles

- Converts each clipped raster into a Cloud-Optimized GeoTIFF (COG)
- Skips if output is newer than input
- COGs use moderate lossless compression (`COMPRESS=ZSTD`, `LEVEL=9`, `PREDICTOR=3`) and disable overviews (`OVERVIEWS=NONE`) to reduce storage usage

```bash
./scripts/cogify.sh
```

### 7. Build VRT mosaics

Builds variable-specific mosaics from COGs using `gdalbuildvrt`:

```bash
./scripts/build_vrt.sh
```

The script is incremental: it rebuilds when source COGs are newer than the target VRT. Use `FORCE=1` to rebuild unconditionally.

### 8. Run the API

This exposes both the API and a Terracotta tile server:

```bash
docker compose up --build
```

- **GET `/health`** is liveness-only and always returns HTTP 200 with `{ "ok": true, "status": "alive" }`. Docker `HEALTHCHECK` probes this endpoint.
- **GET `/ready`** is readiness and returns:
  - HTTP 200 when DEM is available and `API_KEY` is configured.
  - HTTP 503 when DEM is unavailable or `API_KEY` is not configured.
  - A payload like `{ "ok": false, "dem_ready": true }` when only API key configuration is missing.
- **POST `/elevations`**:
  - Accepts `{ "points": [ {"lat":..,"lng":..}, ... ] }` with zero or more points.
  - Returns the same envelope shape with one point entry per input coordinate.
  - Out-of-coverage points return `status: "out_of_coverage"` in the payload (HTTP 200).

#### Make a request

```bash
curl -H "X-API-Key: dev-local-key" \
  -H "Content-Type: application/json" \
  -X POST "http://localhost:8000/elevations" \
  -d '{"points":[{"lat":46.8139,"lng":-71.2080},{"lat":46.8145,"lng":-71.2050}]}'
```

Response shape:

```json
{
  "version": 1,
  "source": {
    "generated_at": "2026-02-27T15:04:05Z",
    "request_id": "..."
  },
  "line_length_m": 1520.4,
  "points": [
    { "chainage_m": 0.0, "elevation_m": 42.1, "status": "ok" },
    { "chainage_m": 60.0, "elevation_m": null, "status": "nodata" },
    { "chainage_m": 120.0, "elevation_m": null, "status": "out_of_coverage" }
  ],
  "quality": {
    "total": 3,
    "ok": 1,
    "nodata": 1,
    "out_of_coverage": 1,
    "coverage_ratio": 0.3333333333
  }
}
```

Note: Sampling uses **nearest-neighbor** (no bilinear smoothing) for stability and speed.

## Authentication

All data endpoints require an API key via the `X-API-Key` header. The server can start without `API_KEY`, but authenticated data requests return HTTP 503 until `API_KEY` is configured.

## Docker

1. Build the image:

```bash
docker build -f Dockerfile.api -t merit-api .
```

2. Run the container (mount the data folder read-only):

```bash
docker run --rm -p 8000:8000 \
  -e API_KEY="your-secret-key" \
  -e DEM_PATH="/data/mosaic/canada_elv.vrt" \
  -e WEB_CONCURRENCY="2" \
  -v "$(pwd)/data:/data:ro" \
  merit-api
```

3. Verify:

```bash
curl -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -X POST "http://localhost:8000/elevations" \
  -d '{"points":[{"lat":46.8139,"lng":-71.2080}]}'
```

## Production deployment (Disco)

Disco reads `disco.json` at the repo root and builds the API using `Dockerfile.api`.

### Configuration

Required environment variables:

- `DEM_PATH` (required): path to the elevation VRT mosaic (default `/data/mosaic/canada_elv.vrt`)

Optional:

- `API_KEY`: shared secret for `X-API-Key`; required for successful `/elevations` requests
- `ALLOWED_ORIGINS` (default `*`): comma-separated list of origins for CORS
- `MAX_BATCH` (default `1000`): max points in a batch request
- `WEB_CONCURRENCY` (default `2`): gunicorn worker count
- `LOG_LEVEL` (default `info`)


### One-time MERIT data import

Disco volumes are created on first deploy based on `disco.json`. After the first deploy, import only the needed MERIT variable files.

1. Deploy once to create the volume:

```bash
disco deploy --project <your-project> --disco <your-disco>
```

2. Import selected variable datasets into your target volume:

```bash
DISCO=<your-disco> PROJECT=<your-project> VOLUME=<your-volume-id> \
  ./scripts/disco_import_data.sh
```

## Terracotta usage (overlay-first visualization)

Terracotta is configured in this repo for the overlay workflow (`/data/overlays/{tile}_{layer}_{band}.vrt`). It does **not** replace the FastAPI elevation API.

```bash
docker compose up --build terracotta
```

### List datasets

```bash
curl http://127.0.0.1:8080/datasets
```

Example response for the overlay registry:

```json
{ "datasets": [{ "tile": "mosaic", "layer": "elvhypsometric", "band": "r" }], "limit": 100, "page": 0 }
```

### Overlay tile URL template

The viewer uses:

```
http://127.0.0.1:8080/rgb/mosaic/elvhypsometric/{z}/{x}/{y}.png?r=r&g=g&b=b
```

Run these once before serving overlays:

```bash
./scripts/make_hypsometric_overlay.sh
./scripts/build_overlay_band_vrts.sh
```

## Viewer

The repo includes `viewer/index.html`, a simple static viewer with:

- A basemap for context
- The Terracotta elevation tile layer
- Dataset coverage outlines and aggregate bounds derived from Terracotta dataset tile keys
- A live elevation readout that calls FastAPI `POST /elevations` with `X-API-Key`
- An in-page config panel for API base URL, Terracotta base URL, and API key

### Run it

1. Start FastAPI on port 8000: `docker compose up --build`
2. Start Terracotta on port 8080
3. Serve the `viewer/` folder:

```bash
python3 -m http.server 63783 -d viewer
```

Open: `http://localhost:63783/`

The viewer supports three configuration sources (highest priority first):

1. Query params (`?apiBase=...&terracottaBase=...&apiKey=...`)
2. `localStorage` (saved by the in-page config panel)
3. `window.MERIT_CONFIG` template object (`API_BASE`, `TERRACOTTA_BASE`, `API_KEY`)

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
./scripts/build_vrt.sh
```

## Data size & storage

MERIT-Hydro tiles can be large. The workflow stores:

- Raw downloads
- Extracted data
- Clipped tiles
- COGs

After you validate your VRTs and API, you can consider deleting intermediate clips to save space, keeping only:

- `data/canada/elv/cog/`
- `data/mosaic/canada_elv.vrt`

Use this helper to remove intermediate files in one step:

```bash
./scripts/cleanup_intermediate_data.sh
```

It removes:

- `data/raw/extracted/*`
- `data/raw/tifs/*`
- `data/canada/elv/clipped/*`

## Next steps

- Build a tile index to route queries to a single COG instead of a VRT for faster I/O.
- Swap MERIT-Hydro for higher-resolution HRDEM tiles where available.

## Dependency maintenance

- `Dockerfile.terracotta` pins Terracotta to a specific version for reproducible builds.
- Recommended update cadence: review and bump pinned service/runtime dependencies monthly or during planned release windows.

## Tests

Contract tests cover readiness semantics, auth, out-of-bounds handling, and endpoint removal behavior.

```bash
python3 -m pip install -r api/requirements-dev.txt
python3 -m unittest discover -s tests -v
```
