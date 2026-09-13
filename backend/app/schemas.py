"""API response shapes — matches IMPLEMENTATION_PLAN.md section 7."""
import datetime
from pydantic import BaseModel


class DistrictSummary(BaseModel):
    id: str
    name: str
    risk_level: str
    risk_score: float
    last_updated: datetime.datetime | None = None
    # Extends the plan's section 7 schema (which lists only the four fields
    # above) with geometry + centroid: the map screen (section 8) needs a
    # polygon per district, and adding it here avoids an extra detail
    # request per district just to draw the map.
    geometry: dict
    centroid: list[float]

    model_config = {"from_attributes": True}


class SignalBreakdown(BaseModel):
    water_anomaly: float
    rainfall_anomaly: float
    terrain_susceptibility: float
    water_source: str
    rainfall_source: str
    rainfall_3d_mm: float | None = None
    rainfall_7d_mm: float | None = None
    rainfall_baseline_7d_mm: float | None = None


class DistrictDetail(BaseModel):
    id: str
    name: str
    province: str
    risk_level: str
    risk_score: float
    signals: SignalBreakdown
    last_satellite_pass: datetime.datetime | None
    last_updated: datetime.datetime | None
    geometry: dict
    centroid: list[float]
    area_sqkm: float


class HistoryPoint(BaseModel):
    date: datetime.datetime
    risk_score: float
    risk_level: str


class RefreshResult(BaseModel):
    districts_processed: int
    started_at: datetime.datetime
    finished_at: datetime.datetime
    errors: list[str]
