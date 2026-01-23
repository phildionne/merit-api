# MERIT-API

This repo provides an end-to-end workflow to **manually download MERIT-Hydro data**, preprocess it locally with GDAL into **COGs + a VRT mosaic**, and run a **Docker-only FastAPI service** to query elevation by latitude/longitude.

**Important:** MERIT-Hydro downloads require a license/registration. This project **does not** bypass that gate. You must manually accept the license and supply your own download URLs or archives.

## What you get

- Local preprocessing pipeline using GDAL
- Output datasets (default bbox):
  - `data/canada/clipped/*.tif` (bbox clips)
  - `data/canada/cog/*.tif` (COG-optimized GeoTIFFs)
  - `data/mosaic/canada.vrt` (VRT mosaic)
- API
  - `GET /elevation?lat=<float>&lng=<float>`
  - `POST /elevation` with a batch payload

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

```bash
./scripts/check_deps.sh
./scripts/prepare_dirs.sh
```

### 3. Manual download step

- Register/accept MERIT-Hydro license and obtain download credentials
- Download this subset of the data (covers the default bbox -80 to -55 lon, 41 to 63 lat):
  - N60–N90: `elv_n60w090.tar`, `elv_n60w060.tar`
  - N30–N60: `elv_n30w090.tar`, `elv_n30w060.tar`
- Download the required archives and place them in `data/raw/downloads/`

### 4. Unpack and discover

- Unpacks `*.zip` and `*.tar.gz`/`*.tgz` into `data/raw/extracted/`
- Finds all `.tif`/`.tiff` and symlinks them into `data/raw/tifs/`

```bash
./scripts/unpack_and_discover.sh
```

### 5. Clip to bbox

- Clips each input raster to the configured bbox
- Reprojects to EPSG:4326 if needed
- Deletes fully nodata outputs (empty clips)

```bash
./scripts/clip_canada.sh
```

### 6. COGify the clipped tiles

- Converts each clipped raster into a Cloud-Optimized GeoTIFF (COG)
- Skips if output is newer than input

```bash
./scripts/cogify.sh
```

### 7. Build VRT mosaic

Builds `data/mosaic/canada.vrt` from all COGs using `gdalbuildvrt`

```bash
./scripts/build_vrt.sh
```

### 8. Run the API

This exposes both the API and a terracota tile server:

```bash
docker compose up --build
```

- API: `curl "http://localhost:8000/elevation?lat=46.8139&lng=-71.2080"`
- Terracota: `curl ...`

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

## Hypsometric overlay workflow (pre-colored)

This repo can generate a pre-colored elevation overlay (0–1000m ramp) and serve it via Terracotta, with a Leaflet opacity slider.

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

### 4. Viewer overlay + opacity slider

The viewer requests the overlay via the mosaic dataset:

```
http://127.0.0.1:8080/rgb/mosaic/elvhypsometric/{z}/{x}/{y}.png?r=r&g=g&b=b
```

Use the slider in `viewer/index.html` to adjust overlay opacity.

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

After you validate your VRT and API, you can consider deleting `data/raw/extracted` and `data/canada/clipped` to save space, keeping only:

- `data/canada/cog/`
- `data/mosaic/canada.vrt`

## Next steps

- Build a tile index to route queries to a single COG instead of a VRT for faster I/O.
- Swap MERIT-Hydro for higher-resolution HRDEM tiles where available.
