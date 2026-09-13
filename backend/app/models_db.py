"""ORM models — matches the schema in IMPLEMENTATION_PLAN.md section 7."""
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

    snapshots = relationship("RiskSnapshot", back_populates="district", order_by="RiskSnapshot.timestamp")


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    water_anomaly = Column(Float, nullable=False)
    rainfall_anomaly = Column(Float, nullable=False)
    terrain_susceptibility = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)

    rainfall_3d_mm = Column(Float, nullable=True)
    rainfall_7d_mm = Column(Float, nullable=True)
    rainfall_baseline_7d_mm = Column(Float, nullable=True)
    last_satellite_pass = Column(DateTime, nullable=True)

    # Transparency fields (README "honesty" principle): which signals were
    # computed from real data vs. a documented fallback for this snapshot.
    water_source = Column(String, default="mock")       # "mock" | "copernicus_ndwi" | "copernicus_model"
    rainfall_source = Column(String, default="open_meteo")

    district = relationship("District", back_populates="snapshots")
