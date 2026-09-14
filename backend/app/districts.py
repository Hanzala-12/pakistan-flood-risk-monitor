"""Loads config/districts.geojson (built by scripts/build_districts_config.py
+ scripts/compute_terrain_susceptibility.py) into the districts table.
Re-running this is idempotent — it upserts, so re-running the build scripts
and this loader is how you add/adjust districts later without touching code,
per IMPLEMENTATION_PLAN.md section 3."""
import json
import logging
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models_db import District

logger = logging.getLogger(__name__)


def load_districts_geojson() -> dict:
    settings = get_settings()
    with open(settings.districts_geojson_path, encoding="utf-8") as f:
        return json.load(f)


def sync_districts(db: Session) -> int:
    fc = load_districts_geojson()
    count = 0
    for feat in fc["features"]:
        props = feat["properties"]
        if props.get("terrain_susceptibility") is None:
            logger.warning(
                "%s has no terrain_susceptibility — run "
                "scripts/compute_terrain_susceptibility.py before going live.",
                props["id"],
            )
        if props.get("discharge_query_point") is None:
            logger.warning(
                "%s has no discharge_query_point — run scripts/calibrate_discharge_points.py "
                "to enable the live river-discharge signal (falls back to a neutral value until then).",
                props["id"],
            )
        discharge_point = props.get("discharge_query_point")

        existing = db.get(District, props["id"])
        values = dict(
            name=props["name"],
            province=props["province"],
            geometry=feat["geometry"],
            centroid_lon=props["centroid"][0],
            centroid_lat=props["centroid"][1],
            bbox=props["bbox"],
            area_sqkm=props["area_sqkm"],
            terrain_susceptibility=props.get("terrain_susceptibility") or 0.5,
            terrain_mean_elevation_m=props.get("terrain_mean_elevation_m"),
            discharge_query_point_lon=discharge_point[0] if discharge_point else None,
            discharge_query_point_lat=discharge_point[1] if discharge_point else None,
        )
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
        else:
            db.add(District(id=props["id"], **values))
        count += 1
    db.commit()
    return count
