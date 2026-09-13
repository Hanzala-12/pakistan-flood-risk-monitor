"""
One-time static terrain susceptibility computation (IMPLEMENTATION_PLAN.md
section 6.3), run against real SRTM elevation data.

Data source note: the plan suggests Google Earth Engine or USGS
EarthExplorer for SRTM, both of which need an account/credentials this
project doesn't have configured. Instead this script uses opentopodata.org's
public SRTM30m endpoint, which serves the same NASA SRTM data with no
registration or API key required. That keeps this a *real* computation
(actual elevation samples, not fabricated numbers) while staying in the
"free, no manual account setup" spirit of the plan. If you later configure
Google Earth Engine, swap this script's `fetch_elevations` for a GEE
`ee.Reduce.mean()` over the district geometry — the output shape
(terrain_susceptibility, terrain_mean_elevation_m written into
config/districts.geojson) stays the same either way.

Method (documented simplification — see README "Data sourcing decisions"):
  1. Sample an evenly spaced lat/lon grid over each district's bounding box.
  2. Keep only points that fall inside the district polygon (ray casting,
     exterior ring only — holes are ignored, which is fine at this
     district-outline scale).
  3. Query SRTM elevation for each kept point (opentopodata, batched).
  4. mean_elevation = average of sampled elevations.
     relief = max - min of sampled elevations (a coarse ruggedness/slope
     proxy — a real slope raster would be better but needs a full DEM
     download; out of scope for a per-district static score computed from
     a point API).
  5. Normalize mean_elevation and relief across the district set to 0..1
     (min-max), invert (lower elevation & lower relief -> more flood-prone),
     and average the two into terrain_susceptibility.

Known limitation, stated plainly rather than hidden: this v1 terrain score
does NOT include distance-to-major-river, which the plan calls out as a
useful factor. That needs a hydrology layer (e.g. HydroRIVERS) this script
doesn't pull in. Every district in this v1 scope already sits directly in
the Indus floodplain, so elevation + relief alone is a reasonable proxy for
now; adding river-distance is a clearly-labeled v1.1 TODO, not a silent gap.

Usage:
    python scripts/compute_terrain_susceptibility.py
"""
import json
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRICTS_PATH = REPO_ROOT / "config" / "districts.geojson"

OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm90m"
BATCH_SIZE = 90          # opentopodata public instance caps at 100 locations/request
REQUEST_DELAY_S = 1.1    # public instance rate limit is ~1 req/sec
GRID_STEP_DEG = 0.12     # ~13km at this latitude; coarse but fine for a static district-level score


def point_in_ring(lon, lat, ring):
    """Standard ray-casting point-in-polygon test against one [lon, lat] ring."""
    inside = False
    n = len(ring)
    x, y = lon, lat
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lon, lat, geometry):
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for poly in polys:
        exterior = poly[0]
        if point_in_ring(lon, lat, exterior):
            return True
    return False


def sample_grid(bbox, geometry, step=GRID_STEP_DEG):
    min_lon, min_lat, max_lon, max_lat = bbox
    points = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            if point_in_geometry(lon, lat, geometry):
                points.append((lon, lat))
            lon += step
        lat += step
    if not points:
        # Fallback: bbox center, in case the grid step skipped a narrow district
        points.append(((min_lon + max_lon) / 2, (min_lat + max_lat) / 2))
    return points


def fetch_elevations(points):
    elevations = []
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i:i + BATCH_SIZE]
        locs = "|".join(f"{lat},{lon}" for lon, lat in batch)
        url = f"{OPENTOPODATA_URL}?locations={locs}"
        req = Request(url, headers={"User-Agent": "flood-risk-monitor/1.0"})
        for attempt in range(3):
            try:
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except (HTTPError, URLError) as e:
                wait = 2 ** attempt
                print(f"  request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
        else:
            raise RuntimeError(f"opentopodata request failed after retries: {url}")

        for r in data["results"]:
            if r["elevation"] is not None:
                elevations.append(r["elevation"])
        time.sleep(REQUEST_DELAY_S)
    return elevations


def minmax_norm(values):
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def main():
    with open(DISTRICTS_PATH, encoding="utf-8") as f:
        fc = json.load(f)

    stats = []
    for feat in fc["features"]:
        props = feat["properties"]
        print(f"Sampling elevation for {props['name']}...")
        points = sample_grid(props["bbox"], feat["geometry"])
        elevations = fetch_elevations(points)
        mean_elev = sum(elevations) / len(elevations)
        relief = max(elevations) - min(elevations)
        print(f"  {len(points)} sample points -> mean {mean_elev:.1f}m, relief {relief:.1f}m")
        stats.append({"id": props["id"], "mean_elev": mean_elev, "relief": relief})

    mean_norms = minmax_norm([s["mean_elev"] for s in stats])
    relief_norms = minmax_norm([s["relief"] for s in stats])

    by_id = {feat["properties"]["id"]: feat for feat in fc["features"]}
    for s, mean_norm, relief_norm in zip(stats, mean_norms, relief_norms):
        # Invert: lower elevation & lower relief -> higher flood susceptibility.
        susceptibility = round(1 - (0.6 * mean_norm + 0.4 * relief_norm), 3)
        props = by_id[s["id"]]["properties"]
        props["terrain_susceptibility"] = susceptibility
        props["terrain_mean_elevation_m"] = round(s["mean_elev"], 1)
        props["terrain_relief_m"] = round(s["relief"], 1)
        props["terrain_method"] = "SRTM90m point samples via opentopodata.org; normalized (elevation, relief) across v1 district set"

    with open(DISTRICTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    print(f"\nUpdated {len(stats)} districts in {DISTRICTS_PATH}")
    for s in sorted(stats, key=lambda x: by_id[x["id"]]["properties"]["terrain_susceptibility"], reverse=True):
        p = by_id[s["id"]]["properties"]
        print(f"  {p['name']:22s} susceptibility={p['terrain_susceptibility']:.3f}  mean_elev={p['terrain_mean_elevation_m']}m  relief={p['terrain_relief_m']}m")


if __name__ == "__main__":
    main()
