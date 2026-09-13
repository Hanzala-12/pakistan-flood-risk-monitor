import numpy as np

from app.ingestion.satellite_copernicus import compute_ndwi_water_fraction


def test_ndwi_all_water():
    # Water: green > nir -> NDWI > 0
    green = np.full((10, 10), 200.0)
    nir = np.full((10, 10), 50.0)
    assert compute_ndwi_water_fraction(green, nir) == 1.0


def test_ndwi_all_land():
    # Vegetation/land: nir > green -> NDWI < 0
    green = np.full((10, 10), 50.0)
    nir = np.full((10, 10), 200.0)
    assert compute_ndwi_water_fraction(green, nir) == 0.0


def test_ndwi_mixed_scene():
    green = np.full((10, 10), 50.0)
    nir = np.full((10, 10), 200.0)
    green[:5, :] = 200.0  # top half is water
    nir[:5, :] = 50.0
    assert compute_ndwi_water_fraction(green, nir) == 0.5


def test_ndwi_handles_zero_denominator():
    green = np.zeros((3, 3))
    nir = np.zeros((3, 3))
    # should not raise (division-by-zero guarded), result is well-defined
    frac = compute_ndwi_water_fraction(green, nir)
    assert 0.0 <= frac <= 1.0
