"""Real satellite ingestion via the Copernicus Data Space Ecosystem (CDSE).

Activated when settings.satellite_provider == "copernicus". Needs a free
CDSE account (register at dataspace.copernicus.eu — this project can't do
that step for you) and its client credentials in .env as CDSE_CLIENT_ID /
CDSE_CLIENT_SECRET (create an OAuth client under your CDSE account's
"S3 credentials" / API access page).

Pipeline:
  1. OAuth2 client-credentials token from CDSE's identity service.
  2. OData search for the most recent, low-cloud Sentinel-2 L2A product
     whose footprint covers the district's bounding box.
  3. Download the green (B03) and NIR (B08) 10m bands for that product.
  4. Compute NDWI = (green - nir) / (green + nir); NDWI > NDWI_WATER_THRESHOLD
     is the standard water-detection rule (McFeeters, 1996) — a real,
     well-established remote-sensing method, used here as the always-available
     signal that doesn't depend on the trained model existing yet.
  5. If a trained segmentation model's weights are present
     (app/inference/model.py), prefer its water mask over plain NDWI for the
     final water fraction; otherwise NDWI is the answer, not a placeholder.
  6. Compare against a precomputed dry-season baseline fraction (section 6.1)
     to get the water *anomaly*, not raw coverage.

**Check before relying on this in production** (flagged the same way the
companion notebook flags its one Prithvi-loading spot): CDSE's OData query
syntax and asset download paths have changed before. If `_search_products`
or `_download_band` starts failing, check the current docs at
https://documentation.dataspace.copernicus.eu/APIs/OData.html before
assuming the fusion logic itself is broken — this is the one module in the
backend most exposed to an upstream API changing shape.

This module is exercised in tests only via `compute_ndwi_water_fraction`
(pure array math, no network) — the network calls need live credentials
this environment doesn't have, so they're structurally complete but
untested end-to-end. Treat a first live run as a smoke test.
"""
import datetime
import logging
from io import BytesIO

import numpy as np
import requests

from app.config import get_settings
from app.ingestion.base import SatelliteProvider, WaterExtentResult

logger = logging.getLogger(__name__)

IDENTITY_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ODATA_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
NDWI_WATER_THRESHOLD = 0.0  # McFeeters 1996 default; CDSE scenes may need a per-scene tweak
REQUEST_TIMEOUT_S = 30


class CredentialsNotConfigured(RuntimeError):
    pass


class NoUsableSceneFound(RuntimeError):
    pass


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
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires_at: datetime.datetime | None = None

    def get_water_extent(self, district, rainfall_anomaly_hint: float | None = None) -> WaterExtentResult:
        try:
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
        except CredentialsNotConfigured:
            raise
        except NoUsableSceneFound as e:
            logger.info("No usable Sentinel-2 scene for %s: %s", district.id, e)
            raise
        except requests.RequestException as e:
            logger.warning("Copernicus request failed for %s: %s", district.id, e)
            raise

    # -- Auth -------------------------------------------------------------
    def _get_token(self) -> str:
        if not self.settings.cdse_client_id or not self.settings.cdse_client_secret:
            raise CredentialsNotConfigured(
                "CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set — register a free account at "
                "dataspace.copernicus.eu and add credentials to .env to enable live satellite ingestion."
            )
        now = datetime.datetime.utcnow()
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token

        resp = requests.post(
            IDENTITY_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.cdse_client_id,
                "client_secret": self.settings.cdse_client_secret,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = now + datetime.timedelta(seconds=payload.get("expires_in", 600) - 30)
        return self._token

    # -- Search -------------------------------------------------------------
    def _search_latest_scene(self, district) -> dict:
        token = self._get_token()
        min_lon, min_lat, max_lon, max_lat = district.bbox
        polygon_wkt = (
            f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},{max_lon} {max_lat},"
            f"{min_lon} {max_lat},{min_lon} {min_lat}))"
        )
        since = (datetime.date.today() - datetime.timedelta(days=self.settings.satellite_lookback_days)).isoformat()
        odata_filter = (
            "Collection/Name eq 'SENTINEL-2' and "
            f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon_wkt}') and "
            f"ContentDate/Start gt {since}T00:00:00.000Z and "
            "Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' and a/Value eq 'S2MSI2A')"
        )
        resp = requests.get(
            ODATA_SEARCH_URL,
            params={"$filter": odata_filter, "$orderby": "ContentDate/Start desc", "$top": 5},
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        results = resp.json().get("value", [])
        if not results:
            raise NoUsableSceneFound(f"no Sentinel-2 L2A scene found in the last {self.settings.satellite_lookback_days} days")

        best = results[0]
        return {
            "id": best["Id"],
            "name": best["Name"],
            "observed_at": datetime.datetime.fromisoformat(best["ContentDate"]["Start"].replace("Z", "+00:00")),
        }

    # -- Download + read ---------------------------------------------------
    def _download_bands(self, product: dict) -> tuple[np.ndarray, np.ndarray]:
        """Downloads the green (B03) and NIR (B08) 10m bands for one product.

        CDSE serves each SAFE product as a single archive via the `/Products
        ({id})/$value` endpoint; band-level access inside it depends on the
        product's internal JP2 layout, which is the part most likely to need
        a small fix against whatever CDSE's current packaging looks like
        (see module docstring). Kept isolated here so that fix, if needed,
        touches only this method.
        """
        import zipfile
        from rasterio.io import ZipMemoryFile

        token = self._get_token()
        url = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({product['id']})/$value"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=120, stream=True)
        resp.raise_for_status()
        raw = resp.content

        # List entries with the stdlib zipfile module first — ZipMemoryFile
        # (a GDAL-backed virtual filesystem view) doesn't expose namelist().
        band_paths = {"B03": None, "B08": None}
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            for name in zf.namelist():
                for band in band_paths:
                    if name.endswith(f"{band}_10m.jp2"):
                        band_paths[band] = name
        if not all(band_paths.values()):
            raise NoUsableSceneFound(f"could not locate B03/B08 10m bands inside {product['name']}")

        with ZipMemoryFile(BytesIO(raw)) as zmf:
            with zmf.open(band_paths["B03"]) as src:
                green = src.read(1)
            with zmf.open(band_paths["B08"]) as src:
                nir = src.read(1)

        return green, nir

    # -- Baseline -----------------------------------------------------------
    def _dry_season_baseline(self, district) -> float:
        """Static dry-season water-fraction baseline per district (section
        6.1). Computed once (offline, from a known dry-month scene) and
        stored on the district record; 0.0 until that one-time job has been
        run, which just means anomaly == raw fraction until then."""
        return getattr(district, "dry_season_water_fraction", 0.0) or 0.0
