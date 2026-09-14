"""Sentinel1SarProvider orchestration — no live network/S3/GDAL calls here;
those are covered by compute_sar_water_fraction's pure-math tests
(test_sar_water_fraction.py) plus live verification done while building this
(see satellite_sentinel1.py's docstring). This file mocks
_search_candidate_scenes and _download_vv_window to test the multi-candidate
fallback logic itself."""
import datetime
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.ingestion.cdse_client import NoUsableSceneFound
from app.ingestion.satellite_sentinel1 import Sentinel1SarProvider


@dataclass
class FakeDistrict:
    id: str = "sukkur"
    bbox: tuple = (68.0, 27.0, 69.0, 28.0)


def _scene(name):
    return {"id": name, "name": name, "s3_path": f"/eodata/{name}", "observed_at": datetime.datetime(2026, 9, 14)}


def _full_coverage_array():
    # Bimodal, fully valid (no nodata) — clean high-coverage scene.
    arr = np.full((20, 20), 3000, dtype=np.uint16)
    arr[:10, :] = 50
    return arr


def _poor_coverage_array():
    # Mostly nodata (swath-edge padding) — should be rejected and skipped.
    arr = np.zeros((20, 20), dtype=np.uint16)
    arr[:2, :] = 3000  # only 10% valid
    return arr


def test_uses_first_candidate_when_coverage_is_good():
    provider = Sentinel1SarProvider(auth=MagicMock())
    with patch.object(provider, "_search_candidate_scenes", return_value=[_scene("first"), _scene("second")]):
        with patch.object(provider, "_download_vv_window", return_value=_full_coverage_array()) as mock_dl:
            result = provider.get_water_extent(FakeDistrict())

    mock_dl.assert_called_once()  # never even looked at the second candidate
    assert result.source == "sentinel1_sar"
    assert 0.0 <= result.water_anomaly <= 1.0


def test_falls_through_to_second_candidate_when_first_has_poor_coverage():
    provider = Sentinel1SarProvider(auth=MagicMock())
    with patch.object(provider, "_search_candidate_scenes", return_value=[_scene("first"), _scene("second")]):
        with patch.object(provider, "_download_vv_window", side_effect=[_poor_coverage_array(), _full_coverage_array()]):
            result = provider.get_water_extent(FakeDistrict())

    assert result.source == "sentinel1_sar"


def test_raises_when_every_candidate_has_poor_coverage():
    provider = Sentinel1SarProvider(auth=MagicMock())
    with patch.object(provider, "_search_candidate_scenes", return_value=[_scene("first"), _scene("second")]):
        with patch.object(provider, "_download_vv_window", return_value=_poor_coverage_array()):
            with pytest.raises(NoUsableSceneFound):
                provider.get_water_extent(FakeDistrict())


def test_propagates_no_scene_found_from_search():
    provider = Sentinel1SarProvider(auth=MagicMock())
    with patch.object(provider, "_search_candidate_scenes", side_effect=NoUsableSceneFound("no scenes at all")):
        with pytest.raises(NoUsableSceneFound):
            provider.get_water_extent(FakeDistrict())
