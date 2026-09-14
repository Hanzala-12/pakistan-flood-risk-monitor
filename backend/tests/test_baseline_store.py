"""baseline_store.py — the DB-backed cache that survives a process restart
(added 2026-09-14 after an in-process-only cache made an Open-Meteo outage
worse than it needed to be — see the module docstring)."""
from app.ingestion.baseline_store import get_cached_baseline, set_cached_baseline


def test_get_returns_none_on_miss(db_session):
    assert get_cached_baseline(db_session, "sukkur", 37, "rainfall") is None


def test_get_returns_none_when_db_is_none():
    # Every caller passes db=None by default (existing tests, direct provider
    # use) — must behave as a pure no-op cache, never raise.
    assert get_cached_baseline(None, "sukkur", 37, "rainfall") is None
    set_cached_baseline(None, "sukkur", 37, "rainfall", 12.3)  # should not raise


def test_set_then_get_round_trips(db_session):
    set_cached_baseline(db_session, "sukkur", 37, "soil", 0.184)
    assert get_cached_baseline(db_session, "sukkur", 37, "soil") == 0.184


def test_set_overwrites_existing_value(db_session):
    set_cached_baseline(db_session, "sukkur", 40, "discharge", 100.0)
    set_cached_baseline(db_session, "sukkur", 40, "discharge", 250.0)
    assert get_cached_baseline(db_session, "sukkur", 40, "discharge") == 250.0


def test_different_kinds_and_weeks_are_independent(db_session):
    set_cached_baseline(db_session, "sukkur", 41, "rainfall", 5.0)
    set_cached_baseline(db_session, "sukkur", 41, "soil", 0.1)
    set_cached_baseline(db_session, "sukkur", 42, "rainfall", 9.0)
    assert get_cached_baseline(db_session, "sukkur", 41, "rainfall") == 5.0
    assert get_cached_baseline(db_session, "sukkur", 41, "soil") == 0.1
    assert get_cached_baseline(db_session, "sukkur", 42, "rainfall") == 9.0
