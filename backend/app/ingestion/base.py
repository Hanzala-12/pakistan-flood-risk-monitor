"""Provider interfaces. The daily job (app/scheduler/jobs.py) depends only on
these, never on a concrete implementation — that's what lets the whole
pipeline run today against mock/free-tier data and switch to fully live
sources later purely through config/settings.py, with no changes to the
fusion logic or API."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime


@dataclass
class WaterExtentResult:
    water_anomaly: float          # 0..1, already compared against a dry-season baseline
    raw_water_fraction: float | None  # % of district flagged water, before baseline comparison
    source: str                    # "mock" | "copernicus_ndwi" | "copernicus_model"
    observed_at: datetime.datetime | None  # None if no usable scene was found


@dataclass
class RainfallResult:
    rainfall_anomaly: float       # 0..1
    rainfall_3d_mm: float
    rainfall_7d_mm: float
    baseline_7d_mm: float
    source: str                    # "mock" | "open_meteo"


class SatelliteProvider(ABC):
    @abstractmethod
    def get_water_extent(self, district, rainfall_anomaly_hint: float | None = None) -> WaterExtentResult:
        """district is an app.models_db.District row (or any object exposing
        id, name, bbox, geometry, centroid_lon, centroid_lat).

        rainfall_anomaly_hint is optional context (today's rainfall anomaly,
        if already computed) — only the mock provider uses it, to make
        synthetic demo data internally consistent; real providers ignore it.
        """
        raise NotImplementedError


class RainfallProvider(ABC):
    @abstractmethod
    def get_rainfall_signal(self, district, as_of: datetime.date) -> RainfallResult:
        raise NotImplementedError
