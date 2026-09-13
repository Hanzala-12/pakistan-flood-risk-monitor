import os
import tempfile
from pathlib import Path

import pytest

# Point the app at an isolated temp SQLite DB and disable the background
# scheduler *before* anything imports app.config, so the lru_cached Settings
# singleton never picks up the developer's real .env / local database.
_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp_db_path).as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SATELLITE_PROVIDER"] = "mock"

from app.config import get_settings  # noqa: E402
get_settings.cache_clear()

from app.db import init_db, SessionLocal  # noqa: E402
from app.districts import sync_districts  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    init_db()
    db = SessionLocal()
    try:
        sync_districts(db)
    finally:
        db.close()
    yield
    from app.db import engine
    engine.dispose()  # release the SQLite file handle before removing it (needed on Windows)
    try:
        os.remove(_tmp_db_path)
    except OSError:
        pass  # best-effort cleanup of a temp file; not worth failing the suite over


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
