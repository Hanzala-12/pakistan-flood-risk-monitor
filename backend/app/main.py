import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db, SessionLocal
from app.districts import sync_districts
from app.routers import districts, health
from app.scheduler.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        count = sync_districts(db)
        logger.info("Synced %d districts from config/districts.geojson", count)
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Pakistan Flood Risk Monitor",
    description="District-level flood risk for Pakistan's Indus-basin flood belt, "
                "fusing satellite water detection, rainfall anomaly, and terrain susceptibility. "
                "See files/IMPLEMENTATION_PLAN.md for the full spec.",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(districts.router)
