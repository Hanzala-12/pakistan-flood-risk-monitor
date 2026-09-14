"""Sentinel-1 SAR (radar) water detection — the resilience path when
Sentinel-2 optical has no usable scene, invoked automatically by
satellite_copernicus.py's CopernicusSatelliteProvider (not meant to be used
standalone in normal operation, though it implements the same
SatelliteProvider interface and works fine on its own).

**Why this exists, verified via research (2026-09-14), not assumed:**
during Pakistan's monsoon — the actual flood season — cloud cover averages
90%+, and optical water-detection misses ~25% of real surface water in
those months (Radar vs optical, PLOS One,
https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0314033).
A comparable open-source Pakistan flood-risk project
(https://github.com/Rohmashakoor/GEE-Pakistan-Flood-Risk-Model) hit this
exact problem mapping the 2022 floods and switched to Sentinel-1 SAR for
that reason: radar penetrates cloud cover, optical doesn't. Verified live
while building this: a Sentinel-1 GRD scene was available for Sukkur from
2026-09-13, one day newer than the Sentinel-2 scene found the same session.

**Method — real, but a documented simplification, same spirit as the NDWI
threshold and the terrain-susceptibility heuristic elsewhere in this
project:** calm open water reflects radar away from the sensor (specular
reflection) and returns very low backscatter, appearing dark; land,
vegetation and urban areas scatter much more of the signal back and appear
brighter. This module thresholds on that contrast using Otsu's method
(1979) — standard, well-established automatic bimodal thresholding, used
here on a log-scaled (pseudo-dB) transform of the raw digital numbers
rather than on radiometrically-calibrated sigma-nought. **This is uncalibrated**:
GRD products need their per-pixel calibration LUT (in
annotation/calibration/) applied to get true, scene-independent sigma0 in
dB — that calibration step is NOT implemented here (real complexity, real
correctness risk to get right without SNAP or a similar tool to
cross-check against, judged not worth the risk for a first version). The
log transform still separates water from non-water well within one scene
(verified: real DN range 0-5887 over Sukkur, clearly bimodal), just don't
treat the *absolute* dB-like numbers this module produces as calibrated
sigma0 — only the water/non-water classification within one scene is
claimed to be meaningful.

**Second honest caveat, worth stating plainly rather than glossing over:**
flooded/irrigated rice paddies are a well-documented false-positive source
for this exact method (calm standing water in a paddy field returns low
backscatter, same as a river) — a genuine limitation of unsupervised SAR
water classification, not fixable by threshold tuning alone (needs a real
land-cover mask to exclude farmland, not implemented here). A raw water
fraction from this module in a district with significant paddy agriculture
should be read as "low-backscatter fraction," which is water *and*
saturated cropland together, not proven to be exclusively river/flood
water. Observed live: Sukkur read 57.9% on 2026-09-13, September being
within Sindh's rice-growing season — plausibly a mix of real river/flood
water and paddy fields, not necessarily 57.9% of the district underwater.

**Georeferencing, verified live, not assumed:** Sentinel-1 GRD products are
NOT map-projected — `rasterio.open()` on the raw measurement GeoTIFF
returns `crs=None` and pixel-space bounds; geolocation is via ~200 Ground
Control Points instead. Standard fix, verified working live: wrap in a
`rasterio.vrt.WarpedVRT(src, crs="EPSG:4326")`, which uses GDAL's own
GCP-based georeferencing (the same mechanism `gdalwarp -geoloc` uses) to
build a real geotransform, then a normal `windows.from_bounds()` read
against the district bbox works. This also avoids downloading the full
~815MB VV band — GDAL's /vsis3/ virtual filesystem streams only the bytes
for the requested window (verified live: ~31s for one district's window,
not the multi-minute full-file download the naive approach would cost).
"""
import logging

import numpy as np
import rasterio
from rasterio.session import AWSSession
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from botocore.exceptions import BotoCoreError, ClientError
import requests

from app.ingestion.base import SatelliteProvider, WaterExtentResult
from app.ingestion.cdse_client import CDSEAuth, NoUsableSceneFound

logger = logging.getLogger(__name__)

SENTINEL1_PRODUCT_FILTER = "Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' and a/Value eq 'IW_GRDH_1S')"
S3_ENDPOINT_HOST = "eodata.dataspace.copernicus.eu"  # host only, no scheme — verified live this is what AWSSession(endpoint_url=...) wants here
NODATA_VALUE = 0
# If less than this fraction of the district-window's pixels have real data
# (the rest is GCP-swath edge padding, verified live: ~58% padding is normal
# for a window that only partly overlaps one scene), the scene doesn't
# usefully cover the district — treat it the same as "no scene found" so the
# caller's fallback chain (or an honest failure) kicks in instead of a
# result computed from mostly-padding pixels.
MIN_VALID_COVERAGE = 0.5


def _otsu_threshold(values: np.ndarray, n_bins: int = 256) -> float:
    """Standard Otsu (1979) automatic thresholding: the value that maximizes
    between-class variance for a bimodal distribution. Implemented directly
    (no new dependency — this is the same algorithm skimage.filters.
    threshold_otsu provides) since this is the only place in the project
    that would otherwise need scikit-image for one function."""
    hist, bin_edges = np.histogram(values, bins=n_bins)
    hist = hist.astype(np.float64)
    bin_mids = (bin_edges[:-1] + bin_edges[1:]) / 2.0

    weight1 = np.cumsum(hist)
    weight2 = np.cumsum(hist[::-1])[::-1]
    # Avoid divide-by-zero for empty leading/trailing bins.
    sum1 = np.cumsum(hist * bin_mids)
    sum2 = np.cumsum((hist * bin_mids)[::-1])[::-1]
    mean1 = np.divide(sum1, weight1, out=np.zeros_like(sum1), where=weight1 > 0)
    mean2 = np.divide(sum2, weight2, out=np.zeros_like(sum2), where=weight2 > 0)

    between_class_variance = weight1[:-1] * weight2[1:] * (mean1[:-1] - mean2[1:]) ** 2
    best_idx = int(np.argmax(between_class_variance))
    return float(bin_mids[best_idx])


def compute_sar_water_fraction(vv_dn: np.ndarray, nodata_value: int = NODATA_VALUE) -> tuple[float, float]:
    """Real, testable core of the SAR method — pure array math, no I/O.
    Returns (water_fraction, valid_coverage_fraction). `vv_dn` is the raw
    uint16 (or similar) digital-number array from the VV band; 0 is nodata
    (swath-edge padding, verified live). See module docstring for the
    uncalibrated-threshold caveat."""
    valid_mask = vv_dn > nodata_value
    coverage = float(np.mean(valid_mask))
    valid = vv_dn[valid_mask]
    if valid.size == 0:
        return 0.0, 0.0

    # Log transform: SAR backscatter is approximately log-normal, so this
    # separates the water/non-water populations far better than raw linear
    # DN would, even without absolute radiometric calibration (see docstring).
    pseudo_db = 10.0 * np.log10(valid.astype(np.float64) ** 2 + 1.0)
    threshold = _otsu_threshold(pseudo_db)
    water_fraction = float(np.mean(pseudo_db < threshold))  # water = LOW backscatter = dark
    return water_fraction, coverage


class Sentinel1SarProvider(SatelliteProvider):
    def __init__(self, auth: CDSEAuth | None = None):
        self.auth = auth or CDSEAuth()
        self.settings = self.auth.settings

    def get_water_extent(self, district, rainfall_anomaly_hint: float | None = None) -> WaterExtentResult:
        try:
            candidates = self._search_candidate_scenes(district)
            best_coverage_seen = 0.0
            for product in candidates:
                vv_array = self._download_vv_window(product, district.bbox)
                water_fraction, coverage = compute_sar_water_fraction(vv_array)
                best_coverage_seen = max(best_coverage_seen, coverage)
                if coverage >= MIN_VALID_COVERAGE:
                    baseline = getattr(district, "dry_season_water_fraction_sar", 0.0) or 0.0
                    anomaly = max(0.0, min(1.0, water_fraction - baseline))
                    return WaterExtentResult(
                        water_anomaly=round(anomaly, 3),
                        raw_water_fraction=round(water_fraction, 3),
                        source="sentinel1_sar",
                        observed_at=product["observed_at"],
                    )
                logger.info(
                    "Sentinel-1 candidate %s only covers %.0f%% of %s's bbox (needs >= %.0f%%) — "
                    "trying the next candidate scene.",
                    product["name"], coverage * 100, district.id, MIN_VALID_COVERAGE * 100,
                )
            raise NoUsableSceneFound(
                f"none of {len(candidates)} recent Sentinel-1 scenes cover enough of {district.id}'s "
                f"bbox with real data (best seen: {best_coverage_seen:.0%}, needs >= {MIN_VALID_COVERAGE:.0%}) "
                "— district likely sits across a swath edge for this orbit pattern"
            )
        except NoUsableSceneFound as e:
            logger.info("No usable Sentinel-1 scene for %s: %s", district.id, e)
            raise
        except (requests.RequestException, BotoCoreError, ClientError, rasterio.errors.RasterioIOError) as e:
            logger.warning("Sentinel-1 request failed for %s: %s", district.id, e)
            raise

    # -- Search -------------------------------------------------------------
    def _search_candidate_scenes(self, district) -> list[dict]:
        return self.auth.search_latest_products(
            collection="SENTINEL-1",
            extra_filter=SENTINEL1_PRODUCT_FILTER,
            bbox=district.bbox,
            lookback_days=self.settings.satellite_lookback_days,
            top=5,
        )

    # -- Download (windowed, not the full ~815MB band) -----------------------
    def _download_vv_window(self, product: dict, bbox: tuple[float, float, float, float]) -> np.ndarray:
        """Reads only the district's bbox window from the VV band, via GDAL's
        /vsis3/ virtual filesystem + a GCP-based WarpedVRT (see module
        docstring — both verified live before writing this)."""
        s3 = self.auth.get_s3_client()
        prefix = product["s3_path"].removeprefix("/eodata/").removeprefix("eodata/") + "/measurement/"
        vv_key = None
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket="eodata", Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".tiff") and "-vv-" in obj["Key"]:
                    vv_key = obj["Key"]
        if vv_key is None:
            raise NoUsableSceneFound(f"could not locate a VV measurement band under {prefix}")

        min_lon, min_lat, max_lon, max_lat = bbox
        vsis3_path = f"/vsis3/eodata/{vv_key}"

        # rasterio.Env refuses AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY passed
        # directly as GDAL config options ("AWS credentials are handled
        # exclusively by boto3" — verified live, a real error, not a guess) —
        # they have to go through an AWSSession instead.
        session = AWSSession(
            aws_access_key_id=self.settings.cdse_s3_access_key,
            aws_secret_access_key=self.settings.cdse_s3_secret_key,
            endpoint_url=S3_ENDPOINT_HOST,
        )
        with rasterio.Env(session=session, AWS_VIRTUAL_HOSTING="FALSE", AWS_HTTPS="YES"):
            with rasterio.open(vsis3_path) as src:
                with WarpedVRT(src, crs="EPSG:4326", resampling=Resampling.nearest) as vrt:
                    window = from_bounds(min_lon, min_lat, max_lon, max_lat, transform=vrt.transform)
                    return vrt.read(1, window=window)
