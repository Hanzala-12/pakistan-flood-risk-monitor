"""ORM models — matches the schema in IMPLEMENTATION_PLAN.md section 7,
extended with two real signals found by researching comparable open-source
flood-risk projects (soil moisture, river discharge — see README "Data
sourcing decisions")."""
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
import datetime

from app.db import Base


class District(Base):
    __tablename__ = "districts"

    id = Column(String, primary_key=True)          # slug, e.g. "dadu"
    name = Column(String, nullable=False)
    province = Column(String, nullable=False)
    geometry = Column(JSON, nullable=False)          # GeoJSON geometry object
    centroid_lon = Column(Float, nullable=False)
    centroid_lat = Column(Float, nullable=False)
    bbox = Column(JSON, nullable=False)               # [min_lon, min_lat, max_lon, max_lat]
    area_sqkm = Column(Float, nullable=False)
    terrain_susceptibility = Column(Float, nullable=False)
    terrain_mean_elevation_m = Column(Float, nullable=True)
    # Calibrated GloFAS river-channel query point (scripts/calibrate_discharge_points.py) —
    # NOT the same as the nearest-river point used for the static terrain score; GloFAS's
    # own channel grid doesn't align with the HydroRIVERS centerline, verified before
    # building this (see that script's docstring). Nullable: a fresh districts.geojson
    # that hasn't been through calibration yet just means no live discharge signal.
    discharge_query_point_lon = Column(Float, nullable=True)
    discharge_query_point_lat = Column(Float, nullable=True)

    snapshots = relationship("RiskSnapshot", back_populates="district", order_by="RiskSnapshot.timestamp")


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    water_anomaly = Column(Float, nullable=False)
    rainfall_anomaly = Column(Float, nullable=False)
    terrain_susceptibility = Column(Float, nullable=False)
    soil_moisture_anomaly = Column(Float, nullable=False, default=0.0)
    river_discharge_anomaly = Column(Float, nullable=False, default=0.0)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)

    rainfall_3d_mm = Column(Float, nullable=True)
    rainfall_7d_mm = Column(Float, nullable=True)
    rainfall_baseline_7d_mm = Column(Float, nullable=True)
    soil_moisture_m3m3 = Column(Float, nullable=True)
    soil_moisture_baseline_m3m3 = Column(Float, nullable=True)
    river_discharge_cms = Column(Float, nullable=True)
    river_discharge_baseline_cms = Column(Float, nullable=True)
    last_satellite_pass = Column(DateTime, nullable=True)

    # Transparency fields (README "honesty" principle): which signals were
    # computed from real data vs. a documented fallback for this snapshot.
    water_source = Column(String, default="mock")       # "mock" | "copernicus_ndwi" | "sentinel1_sar" | "copernicus_model"
    rainfall_source = Column(String, default="open_meteo")
    soil_moisture_source = Column(String, default="open_meteo")
    river_discharge_source = Column(String, default="open_meteo_glofas")

    district = relationship("District", back_populates="snapshots")


class BaselineCache(Base):
    """Persists the (district, ISO week-of-year, signal kind) -> seasonal
    baseline value computed by rainfall_openmeteo.py / hydrology_openmeteo.py.

    Those providers already cache this in-process (avoids refetching 5 years
    of history on every daily refresh within the same week) — this table adds
    the same cache surviving a process restart, which is what made one
    Open-Meteo outage (2026-09-14) worse than it needed to be: a mid-run
    server restart threw away every baseline already fetched that night,
    forcing a full re-fetch on the very next refresh. See README limitations."""
    __tablename__ = "baseline_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    week_of_year = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)  # "rainfall" | "soil" | "discharge"
    value = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("district_id", "week_of_year", "kind", name="uq_baseline_cache_key"),)
