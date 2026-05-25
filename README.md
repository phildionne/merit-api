# MERIT-API

River elevation pipeline based on the MERIT hydro dataset.

This is an end-to-end workflow to **manually download MERIT-Hydro data**, preprocess it locally with GDAL into **COGs + VRT mosaics**, and run a **FastAPI service** to query elevations by latitude/longitude.

## Quickstart: Data

### 1. Install GDAL locally

You need `gdalinfo`, `gdalwarp`, `gdal_translate`, `gdaldem`, `gdalbuildvrt`, `python3`, `curl`, `unzip`, and `tar` available in your `PATH`.

```bash
brew install gdal
```

### 2. Prepare directories

- Validates required tools and prints versions.
- Creates the full data directory layout under `data/`

```bash
./scripts/check_deps.sh
./scripts/prepare_dirs.sh
```

Canonical local elevation layout after bootstrap:

- `data/canada/elv/clipped/`
- `data/canada/elv/cog/`
- `data/mosaic/canada_elv.vrt`

### 3. Manual download step

**Important:** MERIT-Hydro downloads require a license/registration. This project **does not** bypass that gate.

- Register/accept MERIT-Hydro license and obtain download credentials
- Download MERIT archives into `data/raw/downloads/`.
- By default, the processing scripts use a Quebec-focused bbox (`lon -82..-51`, `lat 43..63`):
  - N60–N90: `elv_n60w090.tar`, `elv_n60w060.tar`
  - N30–N60: `elv_n30w090.tar`, `elv_n30w060.tar`

### 4. Unpack and discover

- Unpacks archives into shared `data/raw/extracted/`.
- Finds `.tif`/`.tiff` and symlinks them into shared `data/raw/tifs/`.
- For performance, applies a filename-based bbox prefilter so obvious non-intersecting tiles are not linked for downstream steps.

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
- Skips if the output COG already exists
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

## Quickstart: API

Serve both the API and a Terracotta tile server:

```bash
docker compose up --build
```

Make a request:

```bash
curl -H "X-API-Key: dev-local-key" \
  -H "Content-Type: application/json" \
  -X POST "http://localhost:8000/elevations" \
  -d '{
    "points": [
      {
        "id": "point-0",
        "coordinates": [-71.2080, 46.8139]
      },
      {
        "id": "point-1",
        "coordinates": [-71.2050, 46.8145]
      }
    ]
  }'
```

Example response shape:

```json
{
  "version": 1,
  "source": {
    "generated_at": "2026-03-17T12:00:00.000Z",
    "request_id": "req-123"
  },
  "data": {
    "points": [
      {
        "id": "point-0",
        "elevation_m": 400.0,
        "status": "ok"
      },
      {
        "id": "point-1",
        "elevation_m": null,
        "status": "nodata"
      }
    ]
  },
  "quality": {
    "total": 2,
    "ok": 1,
    "nodata": 1,
    "out_of_coverage": 0,
    "coverage_ratio": 0.5
  }
}
```

API Endpoints:

- **GET `/health`** is liveness-only and always returns HTTP 200 with `{ "ok": true, "status": "alive" }`. Docker `HEALTHCHECK` probes this endpoint.
- **GET `/ready`** is readiness and returns:
  - HTTP 200 with `{ "ok": true, "status": "ready", "checks": { "api_key": true, "dem": true } }` when the service is ready.
  - HTTP 503 with `{ "ok": false, "status": "not_ready", "checks": ... }` when API key or DEM prerequisites are missing.
- **POST `/elevations`**:
  - Accepts a JSON body containing `points`.
  - Each point must include a unique string `id` plus GeoJSON-style `coordinates` in `[lng, lat]` order.
  - Rejects request bodies larger than `MAX_REQUEST_BODY_BYTES` (default `2000000`) with HTTP 413 and `error.code="payload_too_large"`.
  - Returns the original `id` alongside `elevation_m` and `status`; repeated coordinates rounded to 5 decimal places may be sampled once internally and reused.
  - Preserves point order in the response.
  - Aggregates `quality` from the returned point statuses.
  - Out-of-coverage points return `status: "out_of_coverage"` and `elevation_m: null` in the payload (HTTP 200).

Error envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Invalid request payload"
  },
  "request_id": "req_123"
}
```


### Authentication

All data endpoints require an API key via the `X-API-Key` header.

## Production deployment (Railway)

Railway builds the API from `Dockerfile.api`, mounts the persistent DEM volume at `/data`, and exposes the public domain for the FastAPI service.

Railway service configuration is versioned in [`railway.json`](railway.json).

### 1. Install, login, and link the repo

Install the Railway CLI if needed:

```bash
brew install railway
```

Authenticate and confirm the active workspace:

```bash
railway login
railway whoami --json
```

Link this repo to the target Railway project/environment/service:

```bash
railway link
railway status --json
```

### 2. Configure the service

At minimum, set the shared API key:

```bash
railway variable set API_KEY="your-secret-key" --service merit-api
```

If you are creating the service from scratch, `railway.json` already declares the core service shape. In Railway, make sure the service also has:

- builder: `DOCKERFILE`
- dockerfile path: `/Dockerfile.api`
- volume mounted at `/data`
- health check path: `/health`

Verify the current config:

```bash
railway environment config --json
```

### 3. Deploy once to create the service and volume

Deploy the current repo:

```bash
railway up --detach -m "Initial merit-api deploy"
```

Then confirm the service is up:

```bash
railway service status --service merit-api --json
railway logs --service merit-api --lines 100 --json
```

The API emits structured JSON logs to `stdout`/`stderr` so Railway can index custom fields. The canonical fields are `level`, `message`, `request_id`, `event`, `path`, `status_code`, and `duration_ms`, which makes filters like `@level:error`, `@event:request_completed`, and `@request_id:<id>` usable in Railway Observability.

### 4. Build the Railway import tarball

Package only the files the API needs on the persistent volume. The production VRT expects the canonical layout below inside the mounted volume:

- `data/mosaic/canada_elv.vrt`
- `data/canada/elv/cog/*.tif`

```bash
tar \
  --exclude='.DS_Store' \
  --exclude='._*' \
  -czf /tmp/merit-api-data.tar.gz \
  -C data \
  mosaic/canada_elv.vrt \
  canada/elv/cog
```

This archive is extracted into `/data` by `scripts/railway_import_data.sh`, so the tarball should contain:

- `mosaic/canada_elv.vrt`
- `canada/elv/cog/*.tif`

You can inspect the archive before upload:

```bash
tar -tzf /tmp/merit-api-data.tar.gz | sed -n '1,40p'
```

### 5. Upload the tarball somewhere Railway can fetch over HTTPS

`scripts/railway_import_data.sh` downloads the archive from inside Railway using either:

- `ARCHIVE_URL` for a single `.tar.gz`
- `ARCHIVE_PART_URLS` for split archive parts

Upload `/tmp/merit-api-data.tar.gz` to any HTTPS-accessible object store or file host that Railway can reach, then copy the signed/public URL.

### 6. Import the data into the Railway volume

Run the import from this repo after the service is linked:

```bash
ARCHIVE_URL='https://example.com/merit-api-data.tar.gz' \
  ./scripts/railway_import_data.sh
```

For large split archives:

```bash
ARCHIVE_PART_URLS='https://example.com/part-aa https://example.com/part-ab' \
  ./scripts/railway_import_data.sh
```

The importer:

- checks archive reachability from Railway
- downloads the archive inside Railway
- extracts it into `/data`
- preserves the `mosaic/` and `canada/` paths expected by the API

### 7. Verify the deployment end to end

Check service state and recent logs:

```bash
railway service status --service merit-api --json
railway logs --service merit-api --lines 200 --json
```

### Configuration

Primary environment variables:

- `API_KEY`: shared secret for `X-API-Key`; required for successful `/elevations` requests and for `/ready` to return HTTP 200
- `DEM_PATH` (default `/data/mosaic/canada_elv.vrt`): path to the elevation VRT mosaic

Optional:

- `ALLOWED_ORIGINS` (default `*`): comma-separated list of origins for CORS
- `MAX_REQUEST_BODY_BYTES` (default `2000000`): maximum HTTP request body size accepted by the API
- `PORT` (default `8000` in the container): bind port used by gunicorn and the container health check
- `WEB_CONCURRENCY` (default `1`): gunicorn worker count
- `LOG_LEVEL` (default `info`)
- `MERIT_TRUST_X_REQUEST_ID` (default `true`): when enabled, echoes a caller-supplied `X-Request-ID`; otherwise generates a new request ID
- `MERIT_ENABLE_DOCS` (default `true`): enables FastAPI `/docs`, `/redoc`, and `/openapi.json`

Import script variables:

- `ARCHIVE_URL`: HTTPS URL for a single `.tar.gz` archive to import into Railway
- `ARCHIVE_PART_URLS`: space-separated HTTPS URLs for split archive parts; use this instead of `ARCHIVE_URL`
- `DEST` (default `/data`): extraction destination inside the Railway volume
- `ARCHIVE_PATH` (default `/tmp/data.tar.gz`): temporary archive path inside the Railway container

Processing script overrides:

- `BBOX_MIN_LON`, `BBOX_MIN_LAT`, `BBOX_MAX_LON`, `BBOX_MAX_LAT`: override the default Quebec-focused clip bbox used by `scripts/unpack_and_discover.sh` and `scripts/clip_quebec.sh`
- `PARALLEL` (default `4`): number of parallel clip jobs used by `scripts/clip_quebec.sh`
- `FORCE=1`: forces re-extraction in `scripts/unpack_and_discover.sh` and unconditional VRT rebuilds in `scripts/build_vrt.sh`

Smoke test variables:

- `API_URL` (default `http://localhost:8000`): base URL checked by `scripts/smoke_test.sh`
- `SMOKE_API_KEY` or `API_KEY`: API key used by authenticated smoke checks


## Terracotta

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

1. Start FastAPI and Terracotta: `docker compose up --build`
2. Serve the `viewer/` folder:

```bash
python3 -m http.server 63783 -d viewer
```

Open: `http://localhost:63783/`

The viewer supports three configuration sources (highest priority first):

1. Query params (`?apiBase=...&terracottaBase=...&apiKey=...`)
2. `localStorage` (saved by the in-page config panel)
3. `window.MERIT_CONFIG` template object (`API_BASE`, `TERRACOTTA_BASE`, `API_KEY`)

## Hypsometric overlay workflow

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

Contract tests cover readiness semantics, auth, batch response shape, out-of-bounds handling, and endpoint removal behavior.

```bash
make sync
make ci
```

For narrower local checks:

```bash
make fmt
make fmt-check
make lint
make typecheck
make test
```

The equivalent `uv` commands remain:

```bash
UV_CACHE_DIR=.uv-cache uv sync --locked --group dev
UV_CACHE_DIR=.uv-cache uv run ruff format --check src tests scripts
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run basedpyright --project basedpyrightconfig.json
UV_CACHE_DIR=.uv-cache uv run pytest -q tests
```

Ruff formatting, Ruff linting, and BasedPyright are enforced in CI. The current BasedPyright policy uses `failOnWarnings: true` on the active ruleset, while a narrower set of higher-noise diagnostic categories remains intentionally suppressed in `basedpyrightconfig.json` for future cleanup.
