"""Backfill N days of history so the trend chart isn't empty on day one
(IMPLEMENTATION_PLAN.md section 11, Phase 4).

Rainfall is real historical data (Open-Meteo's archive endpoint, correctly
keyed to each backfilled date — see app/ingestion/rainfall_openmeteo.py).
Water anomaly still comes from the mock satellite provider even here,
because there's no way to retroactively "observe" Sentinel imagery for
1000s of past district-days without the Copernicus archive search this
script isn't doing — this is seed/demo data for the trend chart, not a
claim of historical satellite reprocessing, and every row is stamped
water_source="mock" same as a live mock-mode refresh so the API/app never
present it as something it isn't.

Usage (from repo root, with the backend importable):
    cd backend && PYTHONPATH=. python ../scripts/seed_history.py --days 30
"""
import argparse
import datetime
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14, help="how many past days to backfill (default 14)")
    args = parser.parse_args()

    from app.db import init_db, SessionLocal
    from app.districts import sync_districts
    from app.models_db import District, RiskSnapshot
    from app.scheduler.jobs import refresh_district

    init_db()
    db = SessionLocal()
    try:
        sync_districts(db)
        districts = db.query(District).all()
        today = datetime.date.today()

        for offset in range(args.days, 0, -1):
            as_of = today - datetime.timedelta(days=offset)
            logger.info("Backfilling %s...", as_of.isoformat())
            for district in districts:
                already_seeded = (
                    db.query(RiskSnapshot)
                    .filter(
                        RiskSnapshot.district_id == district.id,
                        RiskSnapshot.timestamp == datetime.datetime.combine(as_of, datetime.time(hour=2)),
                    )
                    .first()
                )
                if already_seeded:
                    continue  # re-running the script is idempotent, not additive
                try:
                    refresh_district(db, district, as_of=as_of)
                except Exception:
                    logger.exception("Failed to backfill %s for %s", district.id, as_of)

        logger.info("Done. Backfilled %d days for %d districts.", args.days, len(districts))
    finally:
        db.close()


if __name__ == "__main__":
    main()
