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
    result = fuse_risk(0.0, 0.0, 0.0)
    assert result.risk_score == 0.0
    assert result.risk_level == "Low"


def test_fuse_risk_all_one_is_severe():
    result = fuse_risk(1.0, 1.0, 1.0)
    assert result.risk_score == 1.0
    assert result.risk_level == "Severe"


def test_fuse_risk_is_weighted_average():
    result = fuse_risk(water_anomaly=0.9, rainfall_anomaly=0.1, terrain_susceptibility=0.5)
    # weights are ~0.33 each -> roughly the mean of the three inputs
    assert 0.4 < result.risk_score < 0.55


@pytest.mark.parametrize("bad_value", [-0.01, 1.01, 2.0, -5])
def test_fuse_risk_rejects_out_of_range_inputs(bad_value):
    with pytest.raises(ValueError):
        fuse_risk(bad_value, 0.5, 0.5)
