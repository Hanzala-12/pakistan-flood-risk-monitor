"""
Adds a real distance-to-major-river term to terrain susceptibility, closing the
gap the README documented as a known v1 limitation (IMPLEMENTATION_PLAN.md
section 6.3 calls out distance-to-major-river as a useful factor;
compute_terrain_susceptibility.py explicitly didn't include it).

Run this AFTER compute_terrain_susceptibility.py — it reads the elevation/relief
scores that script already wrote and recomputes the blended terrain_susceptibility
to include this new term, rather than replacing what's there.

Data source: HydroRIVERS v1.0 (HydroSHEDS, hydrosheds.org) — a free, no-registration
global river network with per-segment average discharge, used here instead of the
plan's other terrain sources for the same reason terrain/rainfall used free
no-auth sources: it's genuinely accessible today. Credit where due: this specific
dataset choice came from looking at other Pakistan flood-risk projects on GitHub
before building this — isham-s/FloodShield uses HydroRIVERS/HydroSHEDS for the
same purpose, which is what pointed here rather than a longer search through
hydrology data sources. Downloads the Asia regional
shapefile once (~90MB), filters to segments crossing this project's district
bounding box, keeps only high-discharge ("major") rivers, and computes the
minimum distance from each district polygon to the nearest one.

Needs shapely + pyshp, which are NOT in backend/requirements.txt (the backend
never touches this at runtime — it's a one-time/occasional maintenance script,
same category as build_districts_config.py). Set up an isolated env for it:
    cd scripts && python -m venv .venv && .venv\\Scripts\\activate
    pip install -r requirements.txt
    python compute_river_proximity.py

Honest finding worth stating plainly rather than glossing over: 12 of this
project's 14 districts already sit directly on (0.0 km from) a major river.
That's expected, not a bug — the plan's whole district list was selected
*because* these districts are in the Indus floodplain (IMPLEMENTATION_PLAN.md
section 3), so most of them were never going to be far from the river network
that defines that floodplain. This term mainly adds real, verified data and
distinguishes the two districts that aren't river-adjacent (Jacobabad, Qambar
Shahdadkot, ~13km out) — it was never going to dramatically reorder a district
list that was pre-filtered for river proximity in the first place.
"""
import io
import json
import pickle
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRICTS_PATH = REPO_ROOT / "config" / "districts.geojson"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

HYDRORIVERS_URL = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip"
SHP_BASENAME = "HydroRIVERS_v10_as_shp/HydroRIVERS_v10_as"

# "Major river" cutoff: average discharge (m^3/s). Verified against this
# project's actual AOI — at this threshold ~540 of the ~22,800 segments in the
# district bounding box survive, isolating the Indus mainstem and its largest
# tributaries rather than every minor stream. There's no universal standard
# value for this; it's a documented choice, same spirit as the fusion weights
# in app/fusion/risk.py.
MAJOR_RIVER_DISCHARGE_CMS = 500

# Distance decay constant (km) for converting distance -> a 0..1 proximity
# score: score = exp(-distance_km / DECAY_KM). Deliberately NOT a min-max
# normalization across just these 14 districts — with 12 of them at 0.0 km,
# min-max would make the 2 non-adjacent districts (~13km out) look like they
# have *zero* river exposure, which overstates how different 13km actually is
# in absolute terms. An absolute decay avoids that small-sample distortion.
DECAY_KM = 20.0

# Recombined with the existing elevation/relief-based score. Weights are a
# documented heuristic like the rest of this project's fusion formulas, not a
# fitted or validated value.
WEIGHT_ELEV_RELIEF = 0.65
WEIGHT_RIVER = 0.35


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "flood-risk-monitor/1.0"})
    with urlopen(req, timeout=300) as resp:
        return resp.read()


def download_and_extract_hydrorivers() -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    shp_dir = CACHE_DIR / "HydroRIVERS_v10_as_shp"
    if (shp_dir / "HydroRIVERS_v10_as.shp").exists():
        print("HydroRIVERS already downloaded, reusing cache in scripts/.cache/")
        return CACHE_DIR / SHP_BASENAME

    print(f"Downloading {HYDRORIVERS_URL} (~90MB, one-time)...")
    blob = fetch_bytes(HYDRORIVERS_URL)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(CACHE_DIR)
    print("Extracted to scripts/.cache/")
    return CACHE_DIR / SHP_BASENAME


def bbox_intersects(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def filter_major_rivers_in_aoi(shp_base: Path, aoi: tuple[float, float, float, float]) -> list:
    """Returns a list of shapely LineStrings for major-river segments intersecting
    the AOI bbox. Caches the filtered (much smaller) result so re-runs skip the
    ~1.4M-record full-Asia scan."""
    import shapefile
    from shapely.geometry import LineString

    cache_path = CACHE_DIR / "major_rivers_filtered.pkl"
    if cache_path.exists():
        print("Using cached filtered river segments (scripts/.cache/major_rivers_filtered.pkl)")
        with open(cache_path, "rb") as f:
            raw = pickle.load(f)
    else:
        print("Scanning HydroRIVERS Asia shapefile for segments in the district AOI "
              "(one-time, ~1.4M records, this takes a minute or two)...")
        sf = shapefile.Reader(str(shp_base))
        raw = []
        for sr in sf.iterShapeRecords():
            if bbox_intersects(sr.shape.bbox, aoi):
                raw.append((sr.record["DIS_AV_CMS"], list(sr.shape.points)))
        with open(cache_path, "wb") as f:
            pickle.dump(raw, f)
        print(f"Found {len(raw)} segments in AOI, cached for future runs.")

    major = [LineString(pts) for dis, pts in raw if dis >= MAJOR_RIVER_DISCHARGE_CMS and len(pts) >= 2]
    print(f"{len(major)} segments at or above {MAJOR_RIVER_DISCHARGE_CMS} m^3/s average discharge ('major').")
    return major


def compute_aoi(districts: list) -> tuple[float, float, float, float]:
    bboxes = [d["properties"]["bbox"] for d in districts]
    margin = 1.0  # degrees, to catch nearby major-river reaches just outside a district's own bbox
    return (
        min(b[0] for b in bboxes) - margin,
        min(b[1] for b in bboxes) - margin,
        max(b[2] for b in bboxes) + margin,
        max(b[3] for b in bboxes) + margin,
    )


def main():
    import math
    from shapely.geometry import shape as shapely_shape
    from shapely.ops import nearest_points

    with open(DISTRICTS_PATH, encoding="utf-8") as f:
        fc = json.load(f)
    features = fc["features"]

    aoi = compute_aoi(features)
    shp_base = download_and_extract_hydrorivers()
    major_rivers = filter_major_rivers_in_aoi(shp_base, aoi)
    if not major_rivers:
        raise RuntimeError("No major river segments found in AOI — check MAJOR_RIVER_DISCHARGE_CMS or the AOI bbox.")

    print()
    results = []
    for feat in features:
        props = feat["properties"]
        poly = shapely_shape(feat["geometry"])
        nearest_seg = min(major_rivers, key=lambda seg: poly.distance(seg))
        min_dist_deg = poly.distance(nearest_seg)
        min_dist_km = min_dist_deg * 111.0  # coarse deg->km; fine for a proximity score, not for navigation
        river_score = math.exp(-min_dist_km / DECAY_KM)

        # Also save the actual nearest point's coordinates (not just the distance) —
        # scripts/calibrate_discharge_points.py uses this as a search seed for live
        # river discharge data (a different dataset, GloFAS, needs its own calibration;
        # see that script's docstring for why the two don't share one coordinate).
        _, nearest_point = nearest_points(poly, nearest_seg)
        props["nearest_major_river_point"] = [round(nearest_point.x, 4), round(nearest_point.y, 4)]

        # Read from terrain_susceptibility_base (the pure elevation+relief score from
        # compute_terrain_susceptibility.py), never from terrain_susceptibility itself —
        # that field gets OVERWRITTEN below with the blended result. Reading the blended
        # value back as if it were the pure prior would compound the river term into
        # itself on every re-run (verified: caused real drift, e.g. Dadu 0.769 -> 0.850
        # after just one extra run, before this fix). Falls back to terrain_susceptibility
        # once, for districts.geojson files generated before this field existed.
        prior_susceptibility = props.get("terrain_susceptibility_base", props.get("terrain_susceptibility"))
        if prior_susceptibility is None:
            print(f"  WARNING: {props['id']} has no terrain_susceptibility yet — "
                  f"run compute_terrain_susceptibility.py first. Skipping recombination for this district.")
            combined = river_score
        else:
            props["terrain_susceptibility_base"] = prior_susceptibility  # pin it so future re-runs stay idempotent
            combined = round(WEIGHT_ELEV_RELIEF * prior_susceptibility + WEIGHT_RIVER * river_score, 3)

        props["terrain_river_distance_km"] = round(min_dist_km, 1)
        props["terrain_river_proximity_score"] = round(river_score, 3)
        props["terrain_susceptibility"] = combined
        # Rebuilt fresh each run from terrain_method_base (set once by
        # compute_terrain_susceptibility.py, never touched here) rather than appended to
        # terrain_method directly — same idempotency issue as terrain_susceptibility above,
        # appending to your own previous output duplicates the suffix on every re-run.
        base_method = props.get("terrain_method_base", props.get("terrain_method", ""))
        props["terrain_method_base"] = base_method
        props["terrain_method"] = (
            base_method
            + f"; + distance to nearest major river (HydroRIVERS, >= {MAJOR_RIVER_DISCHARGE_CMS} m^3/s discharge), "
              f"exponential decay (not min-max — see script docstring), blended {WEIGHT_ELEV_RELIEF}/{WEIGHT_RIVER} with prior elevation+relief score"
        )
        results.append((props["name"], min_dist_km, river_score, combined))

    with open(DISTRICTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    print(f"Updated {len(results)} districts in {DISTRICTS_PATH}\n")
    for name, dist_km, river_score, combined in sorted(results, key=lambda r: -r[3]):
        print(f"  {name:22s} river_dist={dist_km:6.1f}km  river_score={river_score:.3f}  susceptibility={combined:.3f}")


if __name__ == "__main__":
    main()
