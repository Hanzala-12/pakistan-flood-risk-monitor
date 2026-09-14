"""API endpoints — IMPLEMENTATION_PLAN.md section 7."""
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_db import District, RiskSnapshot
from app.schemas import DistrictSummary, DistrictDetail, SignalBreakdown, HistoryPoint, RefreshResult
from app.scheduler.jobs import run_daily_refresh

router = APIRouter(prefix="/districts", tags=["districts"])


def _latest_snapshot(db: Session, district_id: str) -> RiskSnapshot | None:
    return (
        db.query(RiskSnapshot)
        .filter(RiskSnapshot.district_id == district_id)
        .order_by(RiskSnapshot.timestamp.desc())
        .first()
    )


@router.get("", response_model=list[DistrictSummary])
def list_districts(db: Session = Depends(get_db)):
    districts = db.query(District).order_by(District.name).all()

    # One query for "latest snapshot per district" instead of N+1 round trips.
    latest_ts_subq = (
        db.query(
            RiskSnapshot.district_id,
            func.max(RiskSnapshot.timestamp).label("max_ts"),
        )
        .group_by(RiskSnapshot.district_id)
        .subquery()
    )
    latest_snapshots = (
        db.query(RiskSnapshot)
        .join(
            latest_ts_subq,
            (RiskSnapshot.district_id == latest_ts_subq.c.district_id)
            & (RiskSnapshot.timestamp == latest_ts_subq.c.max_ts),
        )
        .all()
    )
    snapshot_by_district = {s.district_id: s for s in latest_snapshots}

    result = []
    for d in districts:
        snap = snapshot_by_district.get(d.id)
        result.append(
            DistrictSummary(
                id=d.id,
                name=d.name,
                risk_level=snap.risk_level if snap else "Unknown",
                risk_score=snap.risk_score if snap else 0.0,
                last_updated=snap.timestamp if snap else None,
                geometry=d.geometry,
                centroid=[d.centroid_lon, d.centroid_lat],
            )
        )
    return result


@router.get("/{district_id}", response_model=DistrictDetail)
def get_district(district_id: str, db: Session = Depends(get_db)):
    d = db.get(District, district_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"Unknown district: {district_id}")

    snap = _latest_snapshot(db, district_id)
    if not snap:
        raise HTTPException(
            status_code=409,
            detail=f"District {district_id} has no risk data yet — trigger a refresh first "
                    "(POST /districts/refresh, or wait for the scheduled job).",
        )

    return DistrictDetail(
        id=d.id,
        name=d.name,
        province=d.province,
        risk_level=snap.risk_level,
        risk_score=snap.risk_score,
        signals=SignalBreakdown(
            water_anomaly=snap.water_anomaly,
            rainfall_anomaly=snap.rainfall_anomaly,
            terrain_susceptibility=snap.terrain_susceptibility,
            soil_moisture_anomaly=snap.soil_moisture_anomaly,
            river_discharge_anomaly=snap.river_discharge_anomaly,
            water_source=snap.water_source,
            rainfall_source=snap.rainfall_source,
            soil_moisture_source=snap.soil_moisture_source,
            river_discharge_source=snap.river_discharge_source,
            rainfall_3d_mm=snap.rainfall_3d_mm,
            rainfall_7d_mm=snap.rainfall_7d_mm,
            rainfall_baseline_7d_mm=snap.rainfall_baseline_7d_mm,
            soil_moisture_m3m3=snap.soil_moisture_m3m3,
            soil_moisture_baseline_m3m3=snap.soil_moisture_baseline_m3m3,
            river_discharge_cms=snap.river_discharge_cms,
            river_discharge_baseline_cms=snap.river_discharge_baseline_cms,
        ),
        last_satellite_pass=snap.last_satellite_pass,
        last_updated=snap.timestamp,
        geometry=d.geometry,
        centroid=[d.centroid_lon, d.centroid_lat],
        area_sqkm=d.area_sqkm,
    )


@router.get("/{district_id}/history", response_model=list[HistoryPoint])
def get_district_history(district_id: str, days: int = 30, db: Session = Depends(get_db)):
    d = db.get(District, district_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"Unknown district: {district_id}")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    snapshots = (
        db.query(RiskSnapshot)
        .filter(RiskSnapshot.district_id == district_id, RiskSnapshot.timestamp >= since)
        .order_by(RiskSnapshot.timestamp.asc())
        .all()
    )
    return [HistoryPoint(date=s.timestamp, risk_score=s.risk_score, risk_level=s.risk_level) for s in snapshots]


@router.post("/refresh", response_model=RefreshResult)
def trigger_refresh():
    """Manual trigger for the daily job — useful for demos and for seeding
    the first snapshot right after deployment, without waiting for the
    scheduled time."""
    return run_daily_refresh()
