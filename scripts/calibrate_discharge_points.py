"""
One-time calibration: finds, for each district, the actual GloFAS river-channel
grid cell to query for live discharge data — not just "the nearest point on the
HydroRIVERS centerline," which turns out to be the wrong thing to query.

Why this is needed (verified, not assumed): querying Open-Meteo's Flood API
(GloFAS river discharge) at the exact nearest-river point computed in
compute_river_proximity.py returns 0.00 m^3/s for the Indus near Sukkur — a
river that actually carries thousands of m^3/s. A small grid search around
that point found a cell ~5km away reporting 5983 m^3/s, a plausible real value.
GloFAS has its own internal river-network model at its own grid resolution;
it doesn't share a channel representation with HydroRIVERS (a different
dataset, used here for the static distance-to-river score), so "nearest point
on HydroRIVERS' line" and "the GloFAS cell that's actually on a river" are
related but not identical points. This script finds the real one, once, so
the backend can just query it directly on every refresh instead of re-running
a grid search live.

Method: for each district, search a small grid (5x5, ~0.03 degree steps,
roughly +/-6km) centered on the HydroRIVERS nearest-point already stored in
config/districts.geojson (from compute_river_proximity.py — run that first).
Query today's discharge at every grid point, keep whichever one reports the
highest value (a real river channel cell will read dramatically higher than
adjacent land, which reads ~0) as that district's discharge query point.

Run order: build_districts_config.py -> compute_terrain_susceptibility.py ->
compute_river_proximity.py -> calibrate_discharge_points.py (this script).
No extra dependencies beyond the stdlib — unlike the shapely-based scripts,
this only makes HTTP requests.
"""
import json
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRICTS_PATH = REPO_ROOT / "config" / "districts.geojson"

FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"
GRID_RADIUS = 4           # points in each direction -> 9x9 grid (first pass at radius=2 hit the
                           # edge for most districts, meaning the true peak was outside that grid)
GRID_STEP_DEG = 0.03      # ~3.3km at this latitude
REQUEST_DELAY_S = 0.3


def fetch_discharge(lat: float, lon: float) -> float:
    params = f"latitude={lat}&longitude={lon}&daily=river_discharge&past_days=1&forecast_days=1"
    req = Request(f"{FLOOD_API_URL}?{params}", headers={"User-Agent": "flood-risk-monitor/1.0"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                values = data["daily"]["river_discharge"]
                return max(v for v in values if v is not None) if values else 0.0
        except (HTTPError, URLError) as e:
            time.sleep(1.5 ** attempt)
            last_err = e
    raise RuntimeError(f"Failed to fetch discharge at ({lat},{lon}): {last_err}")


def calibrate_one(lat0: float, lon0: float) -> tuple[float, float, float]:
    """Returns (best_lat, best_lon, best_discharge)."""
    best = (lat0, lon0, -1.0)
    for i in range(-GRID_RADIUS, GRID_RADIUS + 1):
        for j in range(-GRID_RADIUS, GRID_RADIUS + 1):
            lat, lon = lat0 + i * GRID_STEP_DEG, lon0 + j * GRID_STEP_DEG
            discharge = fetch_discharge(lat, lon)
            if discharge > best[2]:
                best = (lat, lon, discharge)
            time.sleep(REQUEST_DELAY_S)
    return best


def main():
    import sys
    only_id = sys.argv[1] if len(sys.argv) > 1 else None  # process one district at a time, for reliable short runs

    with open(DISTRICTS_PATH, encoding="utf-8") as f:
        fc = json.load(f)

    for feat in fc["features"]:
        props = feat["properties"]
        if only_id and props["id"] != only_id:
            continue
        # Re-seed from a previous calibration if one exists (refinement: expands the
        # search outward from a known-good point instead of redoing it from scratch),
        # otherwise start from the HydroRIVERS nearest-point.
        seed_point = props.get("discharge_query_point") or props.get("nearest_major_river_point")
        if not seed_point:
            print(f"  SKIP {props['name']}: no nearest_major_river_point — run compute_river_proximity.py first.")
            continue

        seed_lon, seed_lat = seed_point
        print(f"Calibrating {props['name']} (seed {seed_lat:.3f},{seed_lon:.3f}, 5x5 grid)...")
        best_lat, best_lon, best_discharge = calibrate_one(seed_lat, seed_lon)
        props["discharge_query_point"] = [round(best_lon, 4), round(best_lat, 4)]
        props["discharge_calibration_cms"] = round(best_discharge, 1)
        print(f"  -> ({best_lat:.4f}, {best_lon:.4f}), discharge={best_discharge:.1f} m^3/s "
              f"(moved {abs(best_lat - seed_lat) + abs(best_lon - seed_lon):.3f} deg from seed)")

    with open(DISTRICTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)
    print(f"\nUpdated {DISTRICTS_PATH}")


if __name__ == "__main__":
    main()
