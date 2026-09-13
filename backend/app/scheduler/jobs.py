"""The daily refresh job — IMPLEMENTATION_PLAN.md section 6.5.

For each district: fetch rainfall (real, Open-Meteo), fetch water extent
(mock or Copernicus per settings), fuse into a risk score, write a
risk_snapshots row. One district's failure never aborts the run for the
others — it's logged and the run continues, since a single upstream hiccup
(one bad scene, one flaky request) shouldn't take the whole district list
down.
"""
import datetime
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models_db import District, RiskSnapshot
from app.fusion.risk import fuse_risk
from app.ingestion.rainfall_openmeteo import OpenMeteoRainfallProvider
from app.ingestion.satellite_mock import MockSatelliteProvider
from app.ingestion.base import WaterExtentResult

logger = logging.getLogger(__name__)

_rainfall_provider = OpenMeteoRainfallProvider()
_mock_satellite_provider = MockSatelliteProvider()


def _get_satellite_provider():
    settings = get_settings()
    if settings.satellite_provider == "copernicus":
        from app.ingestion.satellite_copernicus import CopernicusSatelliteProvider
        return CopernicusSatelliteProvider()
    return _mock_satellite_provider


def _get_water_extent(provider, district, rainfall_anomaly: float) -> WaterExtentResult:
    try:
        return provider.get_water_extent(district, rainfall_anomaly_hint=rainfall_anomaly)
    except Exception as e:
        if provider is _mock_satellite_provider:
            raise  # mock provider failing is a real bug, not an expected fallback case
        logger.warning(
            "Live satellite provider failed for %s (%s) — falling back to mock for this run.",
            district.id, e,
        )
        return _mock_satellite_provider.get_water_extent(district, rainfall_anomaly_hint=rainfall_anomaly)


def refresh_district(db: Session, district: District, as_of: datetime.date | None = None) -> RiskSnapshot:
    as_of = as_of or datetime.date.today()
    satellite_provider = _get_satellite_provider()

    rainfall = _rainfall_provider.get_rainfall_signal(district, as_of)
    water = _get_water_extent(satellite_provider, district, rainfall.rainfall_anomaly)

    fusion = fuse_risk(
        water_anomaly=water.water_anomaly,
        rainfall_anomaly=rainfall.rainfall_anomaly,
        terrain_susceptibility=district.terrain_susceptibility,
    )

    snapshot = RiskSnapshot(
        district_id=district.id,
        timestamp=datetime.datetime.combine(as_of, datetime.time(hour=2)),
        water_anomaly=water.water_anomaly,
        rainfall_anomaly=rainfall.rainfall_anomaly,
        terrain_susceptibility=district.terrain_susceptibility,
        risk_score=fusion.risk_score,
        risk_level=fusion.risk_level,
        rainfall_3d_mm=rainfall.rainfall_3d_mm,
        rainfall_7d_mm=rainfall.rainfall_7d_mm,
        rainfall_baseline_7d_mm=rainfall.baseline_7d_mm,
        last_satellite_pass=water.observed_at,
        water_source=water.source,
        rainfall_source=rainfall.source,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def run_daily_refresh() -> dict:
    started_at = datetime.datetime.utcnow()
    errors: list[str] = []
    processed = 0

    db = SessionLocal()
    try:
        districts = db.query(District).all()
        logger.info("Starting daily refresh for %d districts", len(districts))
        for district in districts:
            try:
                snapshot = refresh_district(db, district)
                logger.info("%s -> %s (%.3f)", district.id, snapshot.risk_level, snapshot.risk_score)
                processed += 1
            except Exception as e:
                logger.exception("Failed to refresh %s", district.id)
                errors.append(f"{district.id}: {e}")
    finally:
        db.close()

    finished_at = datetime.datetime.utcnow()
    logger.info("Daily refresh done: %d/%d districts, %d errors", processed, processed + len(errors), len(errors))
    return {
        "districts_processed": processed,
        "started_at": started_at,
        "finished_at": finished_at,
        "errors": errors,
    }
