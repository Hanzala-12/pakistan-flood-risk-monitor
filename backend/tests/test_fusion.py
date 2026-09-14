import pytest

from app.fusion.risk import fuse_risk, risk_level_for_score


def test_risk_level_boundaries():
    assert risk_level_for_score(0.0) == "Low"
    assert risk_level_for_score(0.24) == "Low"
    assert risk_level_for_score(0.25) == "Moderate"
    assert risk_level_for_score(0.49) == "Moderate"
    assert risk_level_for_score(0.5) == "High"
    assert risk_level_for_score(0.74) == "High"
    assert risk_level_for_score(0.75) == "Severe"
    assert risk_level_for_score(1.0) == "Severe"


def test_fuse_risk_all_zero_is_low():
    result = fuse_risk(0.0, 0.0, 0.0, 0.0, 0.0)
    assert result.risk_score == 0.0
    assert result.risk_level == "Low"


def test_fuse_risk_all_one_is_severe():
    result = fuse_risk(1.0, 1.0, 1.0, 1.0, 1.0)
    assert result.risk_score == 1.0
    assert result.risk_level == "Severe"


def test_fuse_risk_is_weighted_average():
    result = fuse_risk(
        water_anomaly=0.9, rainfall_anomaly=0.1, terrain_susceptibility=0.5,
        soil_moisture_anomaly=0.5, river_discharge_anomaly=0.5,
    )
    # weights sum to 1.0 across 5 signals -> result stays within the input range
    assert 0.1 <= result.risk_score <= 0.9


@pytest.mark.parametrize("bad_value", [-0.01, 1.01, 2.0, -5])
def test_fuse_risk_rejects_out_of_range_inputs(bad_value):
    with pytest.raises(ValueError):
        fuse_risk(bad_value, 0.5, 0.5, 0.5, 0.5)


def test_fuse_risk_weights_sum_to_one():
    # If this drifts, every score silently scales — worth pinning explicitly.
    from app.config import get_settings
    settings = get_settings()
    total = (
        settings.fusion_weight_water
        + settings.fusion_weight_rainfall
        + settings.fusion_weight_terrain
        + settings.fusion_weight_soil_moisture
        + settings.fusion_weight_river_discharge
    )
    assert total == pytest.approx(1.0)
