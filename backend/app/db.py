"""SQLAlchemy engine/session setup. SQLite for v1 (IMPLEMENTATION_PLAN.md
section 2) — swapping to Postgres later is a `database_url` change, nothing
in the models or routers needs to know which one is behind it."""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import get_settings

settings = get_settings()

# SQLite needs its parent directory to exist before the file is created, and
# needs check_same_thread=False since FastAPI + APScheduler each touch it
# from their own thread.
if settings.database_url.startswith("sqlite"):
    db_path = settings.database_url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models_db  # noqa: F401  (register models on Base before create_all)
    Base.metadata.create_all(bind=engine)
