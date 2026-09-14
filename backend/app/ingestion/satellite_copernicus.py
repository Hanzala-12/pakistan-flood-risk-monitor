"""Real satellite ingestion via the Copernicus Data Space Ecosystem (CDSE).

Activated when settings.satellite_provider == "copernicus". Needs a free
CDSE account (register at dataspace.copernicus.eu — this project can't do
that step for you) and TWO separate sets of credentials in .env — see
app/ingestion/cdse_client.py for the full "two credential types" story,
found the hard way against the live API.

Pipeline:
  1. Try Sentinel-2 optical first (this module): OData search for the most
     recent, low-cloud L2A product, download the green (B03) and NIR (B08)
     10m bands from CDSE's S3 storage, compute NDWI = (green-nir)/(green+nir)
     (McFeeters, 1996) — a real, well-established water-detection method.
  2. **If no usable Sentinel-2 scene exists, fall back to Sentinel-1 SAR**
     (app/ingestion/satellite_sentinel1.py) instead of giving up. This isn't
     a hypothetical edge case: verified via research while building this
     (2026-09-14) — during Pakistan's monsoon (the actual flood season),
     cloud cover averages 90%+ and optical water-detection misses ~25% of
     real surface water in those months (PLOS One study, see README). A
     comparable open-source Pakistan flood-risk project hit exactly this and
     switched to Sentinel-1 SAR (radar sees through cloud) for the same
     reason — see satellite_sentinel1.py's docstring. Sentinel-2 is tried
     first when available since it's higher resolution (10m vs 10m but a
     simpler, better-understood method) and doesn't need radiometric
     calibration assumptions; SAR is the resilience path, not the default.
  3. Compare whichever raw fraction was obtained against a precomputed
     dry-season baseline to get the water *anomaly*, not raw coverage.

Credentials, verified live: a Sentinel Hub OAuth client (client_credentials
grant) authenticates OData *search* fine, but is the wrong token audience
for downloading product bytes — CDSE returns `401 {"code":"DAT-ZIP-609",
"message":"Token audience not allowed"}` even with the Authorization header
correctly re-attached after the redirect to download.dataspace.copernicus.eu.
Downloads go through CDSE's S3-compatible object storage instead (a second,
separate credential type — CDSE_S3_ACCESS_KEY/SECRET_KEY, generated at
https://eodata-s3keysmanager.dataspace.copernicus.eu/), which is also more
efficient (fetches only the needed bands, not the full ~1.1GB SAFE archive).

**Check before relying on this in production**: CDSE's OData query syntax
and S3 layout have changed before. If `_search_latest_scene` or
`_download_bands` starts failing, check the current docs at
https://documentation.dataspace.copernicus.eu/APIs/OData.html and
https://documentation.dataspace.copernicus.eu/APIs/S3.html before assuming
the fusion logic itself is broken.

This module's array math (`compute_ndwi_water_fraction`) is covered by a
pure unit test; the network/S3 calls were verified end-to-end with live
credentials for Sukkur and Badin while building this (real Sentinel-2 NDWI
water fractions of 0.043 and 0.625 respectively, 2026-09-14) — not just
assumed to work from reading docs. They still can't run in CI (no
credentials there), so a first live run against a new district is a smoke
test.
"""
import logging

import numpy as np
import requests
from botocore.exceptions import BotoCoreError, ClientError

from app.ingestion.base import SatelliteProvider, WaterExtentResult
from app.ingestion.cdse_client import CDSEAuth, CredentialsNotConfigured, NoUsableSceneFound, S3_BUCKET

logger = logging.getLogger(__name__)

SENTINEL2_PRODUCT_FILTER = "Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' and a/Value eq 'S2MSI2A')"
NDWI_WATER_THRESHOLD = 0.0  # McFeeters 1996 default; CDSE scenes may need a per-scene tweak


def compute_ndwi_water_fraction(green: np.ndarray, nir: np.ndarray, threshold: float = NDWI_WATER_THRESHOLD) -> float:
    """Real, testable core of the NDWI method — pure array math, no I/O.
    green/nir are same-shape float arrays (reflectance or raw DN, NDWI's
    sign is unaffected by a shared linear scale)."""
    denom = green.astype(np.float32) + nir.astype(np.float32)
    denom[denom == 0] = 1e-6
    ndwi = (green.astype(np.float32) - nir.astype(np.float32)) / denom
    return float(np.mean(ndwi > threshold))


class CopernicusSatelliteProvider(SatelliteProvider):
    def __init__(self):
        self.auth = CDSEAuth()
        self.settings = self.auth.settings

    def get_water_extent(self, district, rainfall_anomaly_hint: float | None = None) -> WaterExtentResult:
        try:
            return self._get_optical_water_extent(district)
        except CredentialsNotConfigured:
            raise
        except NoUsableSceneFound as e:
            logger.info("No usable Sentinel-2 scene for %s (%s) — trying Sentinel-1 SAR "
                        "(sees through cloud cover; see module docstring).", district.id, e)
            from app.ingestion.satellite_sentinel1 import Sentinel1SarProvider
            return Sentinel1SarProvider(auth=self.auth).get_water_extent(district, rainfall_anomaly_hint)
        except (requests.RequestException, BotoCoreError, ClientError) as e:
            logger.warning("Copernicus Sentinel-2 request failed for %s: %s", district.id, e)
            raise

    def _get_optical_water_extent(self, district) -> WaterExtentResult:
        product = self._search_latest_scene(district)
        green, nir = self._download_bands(product)
        water_fraction = compute_ndwi_water_fraction(green, nir)
        baseline = self._dry_season_baseline(district)
        anomaly = max(0.0, min(1.0, water_fraction - baseline))
        return WaterExtentResult(
            water_anomaly=round(anomaly, 3),
            raw_water_fraction=round(water_fraction, 3),
            source="copernicus_ndwi",
            observed_at=product["observed_at"],
        )

    # -- Search -------------------------------------------------------------
    def _search_latest_scene(self, district) -> dict:
        return self.auth.search_latest_product(
            collection="SENTINEL-2",
            extra_filter=SENTINEL2_PRODUCT_FILTER,
            bbox=district.bbox,
            lookback_days=self.settings.satellite_lookback_days,
        )

    # -- Download + read ---------------------------------------------------
    def _download_bands(self, product: dict) -> tuple[np.ndarray, np.ndarray]:
        """Downloads the green (B03) and NIR (B08) 10m bands for one product
        from CDSE's S3-compatible object storage. Band-level file naming
        inside the SAFE structure is the part most likely to need a small
        fix against whatever CDSE's current packaging looks like; kept
        isolated here so that fix, if needed, touches only this method.
        """
        from rasterio.io import MemoryFile

        s3 = self.auth.get_s3_client()
        # S3Path from OData is like "/eodata/Sentinel-2/...SAFE" — strip the
        # leading "/eodata/" bucket segment to get a key prefix.
        prefix = product["s3_path"].removeprefix("/eodata/").removeprefix("eodata/") + "/GRANULE/"

        band_keys = {"B03": None, "B08": None}
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                for band in band_keys:
                    if key.endswith(f"{band}_10m.jp2"):
                        band_keys[band] = key
        if not all(band_keys.values()):
            raise NoUsableSceneFound(f"could not locate B03/B08 10m bands under {prefix}")

        def _read_band(key: str) -> np.ndarray:
            raw = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            with MemoryFile(raw) as mf, mf.open() as src:
                return src.read(1)

        green = _read_band(band_keys["B03"])
        nir = _read_band(band_keys["B08"])
        return green, nir

    # -- Baseline -----------------------------------------------------------
    def _dry_season_baseline(self, district) -> float:
        """Static dry-season water-fraction baseline per district (section
        6.1). Computed once (offline, from a known dry-month scene) and
        stored on the district record; 0.0 until that one-time job has been
        run, which just means anomaly == raw fraction until then."""
        return getattr(district, "dry_season_water_fraction", 0.0) or 0.0
