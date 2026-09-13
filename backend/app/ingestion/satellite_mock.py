"""Synthetic water-anomaly provider.

Used whenever settings.satellite_provider == "mock" — the default, since
live satellite ingestion needs both a free Copernicus Data Space Ecosystem
account (registration this project can't do on your behalf) and the trained
model weights from the companion Kaggle notebook, neither of which exists
until you set them up. Every value this returns is clearly tagged
source="mock" all the way out to the API response, so the app never shows
synthetic numbers as if they were real satellite observations.

The synthetic value isn't pure noise: it's seeded deterministically per
(district, date) so repeated runs on the same day are stable, and it leans
on the district's terrain susceptibility and (if available) that day's real
rainfall anomaly so a demo/history backfill tells a coherent story — e.g. a
low-lying district after a heavy-rain week shows a plausibly elevated water
anomaly — rather than random-looking noise that would undercut the demo.
"""
import datetime
import hashlib

from app.ingestion.base import SatelliteProvider, WaterExtentResult


def _seeded_unit_random(*parts: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from arbitrary string parts."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class MockSatelliteProvider(SatelliteProvider):
    def get_water_extent(self, district, rainfall_anomaly_hint: float | None = None) -> WaterExtentResult:
        today = datetime.date.today().isoformat()
        noise = _seeded_unit_random(district.id, today, "water")

        base = 0.15 + 0.35 * district.terrain_susceptibility  # flood-prone terrain -> higher baseline "wetness"
        if rainfall_anomaly_hint is not None:
            base += 0.35 * rainfall_anomaly_hint

        water_anomaly = max(0.0, min(1.0, base * 0.7 + noise * 0.3))

        return WaterExtentResult(
            water_anomaly=round(water_anomaly, 3),
            raw_water_fraction=None,
            source="mock",
            observed_at=None,
        )
