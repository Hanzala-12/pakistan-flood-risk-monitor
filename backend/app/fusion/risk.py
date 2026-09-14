"""Transparent, rule-based risk fusion — IMPLEMENTATION_PLAN.md section 6.4.

Deliberately not a trained model: there's no volume of historical ground-truth
"was this district actually flooded" labels to train a fusion model
responsibly on yet. A weighted sum of interpretable 0..1 signals is the
honest v1 — every score can be explained ("high because rainfall was 2.5x
normal and terrain is flood-prone, even though satellite hasn't picked up
standing water yet"), which a black-box fusion model wouldn't give you.
Swapping in a learned fusion model once outcome data exists is a legitimate
v2, not a corner cut here.

Extended from the original 3 signals to 5 after researching comparable
open-source flood-risk projects turned up two more real, no-signup data
sources (soil moisture, river discharge — see README "Data sourcing
decisions" and app/ingestion/hydrology_openmeteo.py).
"""
from dataclasses import dataclass

from app.config import get_settings

RISK_LEVELS = [
    (0.25, "Low"),
    (0.50, "Moderate"),
    (0.75, "High"),
    (1.01, "Severe"),  # upper bound slightly above 1.0 so a score of exactly 1.0 still lands here
]


@dataclass(frozen=True)
class FusionResult:
    risk_score: float
    risk_level: str


def risk_level_for_score(score: float) -> str:
    for upper_bound, label in RISK_LEVELS:
        if score < upper_bound:
            return label
    return "Severe"


def fuse_risk(
    water_anomaly: float,
    rainfall_anomaly: float,
    terrain_susceptibility: float,
    soil_moisture_anomaly: float,
    river_discharge_anomaly: float,
) -> FusionResult:
    settings = get_settings()
    signals = {
        "water_anomaly": water_anomaly,
        "rainfall_anomaly": rainfall_anomaly,
        "terrain_susceptibility": terrain_susceptibility,
        "soil_moisture_anomaly": soil_moisture_anomaly,
        "river_discharge_anomaly": river_discharge_anomaly,
    }
    for name, value in signals.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name}={value!r} must be in [0, 1]")

    score = (
        settings.fusion_weight_water * water_anomaly
        + settings.fusion_weight_rainfall * rainfall_anomaly
        + settings.fusion_weight_terrain * terrain_susceptibility
        + settings.fusion_weight_soil_moisture * soil_moisture_anomaly
        + settings.fusion_weight_river_discharge * river_discharge_anomaly
    )
    score = round(min(1.0, max(0.0, score)), 3)
    return FusionResult(risk_score=score, risk_level=risk_level_for_score(score))
