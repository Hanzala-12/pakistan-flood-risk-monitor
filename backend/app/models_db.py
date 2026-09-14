"""ORM models — matches the schema in IMPLEMENTATION_PLAN.md section 7,
extended with two real signals found by researching comparable open-source
flood-risk projects (soil moisture, river discharge — see README "Data
sourcing decisions")."""
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Integer, JSON
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
    water_source = Column(String, default="mock")       # "mock" | "copernicus_ndwi" | "copernicus_model"
    rainfall_source = Column(String, default="open_meteo")
    soil_moisture_source = Column(String, default="open_meteo")
    river_discharge_source = Column(String, default="open_meteo_glofas")

    district = relationship("District", back_populates="snapshots")
