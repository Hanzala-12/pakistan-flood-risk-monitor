"""
Build config/districts.geojson from OCHA/HDX's Pakistan Common Operational
Dataset for Administrative Boundaries (COD-AB), filtered to the 13-district
v1 scope defined in IMPLEMENTATION_PLAN.md section 3.

Why this source (and not GADM, which the implementation plan also mentions):
GADM's Pakistan level-3 layer (checked at build time) is a 2022 snapshot that
still uses pre-2005/pre-2013 district lines — it has no separate "Qambar
Shahdadkot" (split from Larkana in 2005) or "Sujawal" (split from Thatta in
2013). HDX's cod-ab-pak dataset (OCHA Field Information Services, reviewed
2024) has all 160 current districts, including both of those. Real, current
admin boundaries mattered more here than sticking to the first source named
in the plan, so this script pulls from HDX instead. This is exactly the kind
of substitution the plan expects an engineer to make and document (see
README "Data sourcing decisions").

Deviation from the plan's literal district list: the plan lists "Thatta/
Sujawal" as a single entry (13 districts total). Since they are two distinct
current districts with two distinct polygons, this script keeps them
separate (Sujawal was carved out of Thatta in 2013 and both still sit in the
Indus delta flood belt, so the scoping rationale in section 3 still holds).
That makes the real district count 14, not 13 — noted here and in the
top-level README rather than silently merged.

Usage:
    python scripts/build_districts_config.py

Network access required (fetches ~29MB from data.humdata.org, one time).
Re-run any time to refresh from the upstream dataset.
"""
import io
import json
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "config" / "districts.geojson"

HDX_PACKAGE_ID = "cod-ab-pak"
HDX_API = f"https://data.humdata.org/api/3/action/package_show?id={HDX_PACKAGE_ID}"
GEOJSON_RESOURCE_NAME = "pak_admin_boundaries.geojson.zip"
ADMIN2_MEMBER = "pak_admin2.geojson"

# v1 scope (IMPLEMENTATION_PLAN.md section 3), matched against the dataset's
# `adm2_name` field. Sindh + South Punjab, Indus basin, 2022 flood belt.
TARGET_DISTRICTS = {
    "Dadu": "dadu",
    "Jacobabad": "jacobabad",
    "Kambar Shahdad Kot": "qambar_shahdadkot",
    "Larkana": "larkana",
    "Shikarpur": "shikarpur",
    "Kashmore": "kashmore",
    "Khairpur": "khairpur",
    "Sukkur": "sukkur",
    "Naushahro Feroze": "naushahro_feroze",
    "Badin": "badin",
    "Thatta": "thatta",
    "Sujawal": "sujawal",
    "Dera Ghazi Khan": "dera_ghazi_khan",
    "Rajanpur": "rajanpur",
}

DISPLAY_NAMES = {
    "qambar_shahdadkot": "Qambar Shahdadkot",
    "dera_ghazi_khan": "Dera Ghazi Khan",
    "naushahro_feroze": "Naushahro Feroze",
}


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "flood-risk-monitor/1.0"})
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "flood-risk-monitor/1.0"})
    with urlopen(req, timeout=120) as resp:
        return resp.read()


def find_geojson_zip_url() -> str:
    pkg = fetch_json(HDX_API)
    for res in pkg["result"]["resources"]:
        if res["name"] == GEOJSON_RESOURCE_NAME:
            return res["url"]
    raise RuntimeError(f"Resource {GEOJSON_RESOURCE_NAME} not found in HDX package {HDX_PACKAGE_ID}")


def bbox_of(geometry: dict) -> list:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    lons, lats = [], []
    for poly in polys:
        for ring in poly:
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
    return [min(lons), min(lats), max(lons), max(lats)]


def main():
    print("Fetching HDX package metadata...")
    zip_url = find_geojson_zip_url()
    print("Downloading", zip_url)
    blob = fetch_bytes(zip_url)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        with zf.open(ADMIN2_MEMBER) as f:
            admin2 = json.load(f)

    by_name = {}
    for feat in admin2["features"]:
        name = feat["properties"]["adm2_name"]
        if name in TARGET_DISTRICTS:
            by_name[name] = feat

    missing = set(TARGET_DISTRICTS) - set(by_name)
    if missing:
        raise RuntimeError(f"Districts not found in dataset: {missing}")

    features = []
    for source_name, district_id in TARGET_DISTRICTS.items():
        feat = by_name[source_name]
        props = feat["properties"]
        display_name = DISPLAY_NAMES.get(district_id, source_name)
        out_feat = {
            "type": "Feature",
            "id": district_id,
            "properties": {
                "id": district_id,
                "name": display_name,
                "province": props["adm1_name"],
                "pcode": props["adm2_pcode"],
                "area_sqkm": round(props["area_sqkm"], 1),
                "centroid": [props["center_lon"], props["center_lat"]],
                "bbox": bbox_of(feat["geometry"]),
                "source": "OCHA/HDX cod-ab-pak (data.humdata.org), admin level 2",
                "source_valid_on": props.get("valid_on"),
                # Filled in by scripts/compute_terrain_susceptibility.py — null until that
                # one-time computation has been run.
                "terrain_susceptibility": None,
                "terrain_mean_elevation_m": None,
            },
            "geometry": feat["geometry"],
        }
        features.append(out_feat)

    # Stable order matching the plan's listing (Thatta/Sujawal expanded in place).
    order = [
        "dadu", "jacobabad", "qambar_shahdadkot", "larkana", "shikarpur",
        "kashmore", "khairpur", "sukkur", "naushahro_feroze", "badin",
        "thatta", "sujawal", "dera_ghazi_khan", "rajanpur",
    ]
    features.sort(key=lambda f: order.index(f["id"]))

    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "description": "v1 district scope for the Pakistan Flood Risk Monitor (IMPLEMENTATION_PLAN.md section 3)",
            "source": "OCHA/HDX cod-ab-pak, https://data.humdata.org/dataset/cod-ab-pak",
            "note": "Thatta and Sujawal kept as separate current districts rather than the plan's merged 'Thatta/Sujawal' entry — see scripts/build_districts_config.py docstring.",
            "district_count": len(features),
        },
        "features": features,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    print(f"Wrote {len(features)} districts to {OUT_PATH}")


if __name__ == "__main__":
    main()
