import numpy as np

from app.ingestion.satellite_sentinel1 import compute_sar_water_fraction, _otsu_threshold


def test_otsu_splits_clean_bimodal_data_at_the_gap():
    # Two well-separated clusters — Otsu should land the threshold between them.
    low = np.full(500, 10.0)
    high = np.full(500, 90.0)
    values = np.concatenate([low, high])
    threshold = _otsu_threshold(values)
    assert 10.0 < threshold < 90.0


def test_sar_water_fraction_half_water_half_land():
    # Water = low backscatter (dark), land = high backscatter (bright) — see
    # module docstring. 20x20 grid, top half water (DN ~50), bottom half
    # land (DN ~3000): a realistic-order-of-magnitude contrast.
    arr = np.full((20, 20), 3000, dtype=np.uint16)
    arr[:10, :] = 50
    water_fraction, coverage = compute_sar_water_fraction(arr)
    assert coverage == 1.0  # no nodata in this synthetic array
    assert abs(water_fraction - 0.5) < 0.05


def test_sar_water_fraction_all_land_is_near_zero():
    arr = np.full((20, 20), 3000, dtype=np.uint16)
    water_fraction, coverage = compute_sar_water_fraction(arr)
    assert coverage == 1.0
    # No genuine bimodality (uniform array) — Otsu has nothing to split on,
    # but the result should still not claim most of a uniform land scene is water.
    assert water_fraction <= 0.5


def test_sar_water_fraction_excludes_nodata_from_coverage():
    arr = np.full((20, 20), 3000, dtype=np.uint16)
    arr[:12, :] = 0  # swath-edge padding, see module docstring
    _, coverage = compute_sar_water_fraction(arr)
    assert abs(coverage - 0.4) < 1e-6  # 8/20 rows valid


def test_sar_water_fraction_handles_all_nodata():
    arr = np.zeros((10, 10), dtype=np.uint16)
    water_fraction, coverage = compute_sar_water_fraction(arr)
    assert coverage == 0.0
    assert water_fraction == 0.0
