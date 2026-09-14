"""Shared DB-backed cache for the (district, ISO week-of-year, signal-kind) ->
seasonal-baseline pattern used by rainfall_openmeteo.py and
hydrology_openmeteo.py. Both providers already cache this in-process for the
lifetime of the running server (avoids refetching 5 years of history on every
daily refresh within the same week) — this module adds the same cache
surviving a process restart.

Why this exists: on 2026-09-14, a mid-refresh server restart (needed to pick
up a code fix) threw away every baseline already fetched that run, forcing a
full 5-years-times-14-districts re-fetch right into an ongoing Open-Meteo
outage. An in-process-only cache can't survive that; a DB-backed one can.

`db` is optional and defaults to a no-op cache (returns None / does nothing)
so existing callers and tests that don't pass a session keep working exactly
as before — this is purely additive.
"""
from sqlalchemy.orm import Session

from app.models_db import BaselineCache


def get_cached_baseline(db: Session | None, district_id: str, week_of_year: int, kind: str) -> float | None:
    if db is None:
        return None
    row = (
        db.query(BaselineCache)
        .filter_by(district_id=district_id, week_of_year=week_of_year, kind=kind)
        .first()
    )
    return row.value if row is not None else None


def set_cached_baseline(db: Session | None, district_id: str, week_of_year: int, kind: str, value: float) -> None:
    if db is None:
        return
    row = (
        db.query(BaselineCache)
        .filter_by(district_id=district_id, week_of_year=week_of_year, kind=kind)
        .first()
    )
    if row is not None:
        row.value = value
    else:
        db.add(BaselineCache(district_id=district_id, week_of_year=week_of_year, kind=kind, value=value))
    db.commit()
