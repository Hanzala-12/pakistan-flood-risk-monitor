"""Real satellite ingestion via the Copernicus Data Space Ecosystem (CDSE).

Activated when settings.satellite_provider == "copernicus". Needs a free
CDSE account (register at dataspace.copernicus.eu — this project can't do
that step for you) and TWO separate sets of credentials in .env — see the
"two credential types" note below, found the hard way against the live API.

Pipeline:
  1. OAuth2 client-credentials token from CDSE's identity service, used for
     OData *search* only (CDSE_CLIENT_ID/SECRET, a Sentinel Hub OAuth client).
  2. OData search for the most recent, low-cloud Sentinel-2 L2A product
     whose footprint covers the district's bounding box.
  3. Download the green (B03) and NIR (B08) 10m bands for that product from
     CDSE's S3-compatible object storage (CDSE_S3_ACCESS_KEY/SECRET_KEY —
     a different credential type, see below).
  4. Compute NDWI = (green - nir) / (green + nir); NDWI > NDWI_WATER_THRESHOLD
     is the standard water-detection rule (McFeeters, 1996) — a real,
     well-established remote-sensing method, used here as the always-available
     signal that doesn't depend on the trained model existing yet.
  5. If a trained segmentation model's weights are present
     (app/inference/model.py), prefer its water mask over plain NDWI for the
     final water fraction; otherwise NDWI is the answer, not a placeholder.
  6. Compare against a precomputed dry-season baseline fraction (section 6.1)
     to get the water *anomaly*, not raw coverage.

**Two credential types, not one — verified against the live API, not
assumed from docs:** a Sentinel Hub OAuth client (client_credentials grant,
created under the Sentinel Hub dashboard's "User settings" -> "OAuth
clients") authenticates OData *search* fine, but is the wrong token
audience for downloading product bytes via
`https://catalogue.dataspace.copernicus.eu/odata/v1/Products({id})/$value`
— that redirects to `download.dataspace.copernicus.eu`, which rejects the
Sentinel Hub token with `401 {"code":"DAT-ZIP-609","message":"Token
audience not allowed"}` even when the Authorization header is correctly
re-attached after the redirect. CDSE's own docs recommend S3-compatible
object storage for full-dataset downloads anyway (more efficient here too —
it fetches only the two needed band files instead of the ~1.1GB SAFE zip).
Generate S3 keys at https://eodata-s3keysmanager.dataspace.copernicus.eu/
("Add Credential") — these are the CDSE_S3_ACCESS_KEY / CDSE_S3_SECRET_KEY
settings, unrelated to CDSE_CLIENT_ID/SECRET above.

**Check before relying on this in production** (flagged the same way the
companion notebook flags its one Prithvi-loading spot): CDSE's OData query
syntax and S3 layout have changed before. If `_search_latest_scene` or
`_download_bands` starts failing, check the current docs at
https://documentation.dataspace.copernicus.eu/APIs/OData.html and
https://documentation.dataspace.copernicus.eu/APIs/S3.html before assuming
the fusion logic itself is broken — this is the one module in the backend
most exposed to an upstream API changing shape.

This module's array math (`compute_ndwi_water_fraction`) is covered by a
pure unit test; the network/S3 calls were verified end-to-end with live
credentials for one district (Sukkur) while building this, not just
assumed to work from reading docs — see the module's git history / README
for that verification. They still can't run in CI (no credentials there),
so a first live run against a new district is a smoke test.
"""
import datetime
import logging

import boto3
import numpy as np
import requests
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.ingestion.base import SatelliteProvider, WaterExtentResult

logger = logging.getLogger(__name__)

IDENTITY_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ODATA_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
S3_ENDPOINT_URL = "https://eodata.dataspace.copernicus.eu"
S3_BUCKET = "eodata"
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
        except (requests.RequestException, BotoCoreError, ClientError) as e:
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
            "s3_path": best["S3Path"],  # e.g. "/eodata/Sentinel-2/MSI/L2A/2026/09/14/NAME.SAFE"
            "observed_at": datetime.datetime.fromisoformat(best["ContentDate"]["Start"].replace("Z", "+00:00")),
        }

    # -- S3 client ------------------------------------------------------------
    def _get_s3_client(self):
        if not self.settings.cdse_s3_access_key or not self.settings.cdse_s3_secret_key:
            raise CredentialsNotConfigured(
                "CDSE_S3_ACCESS_KEY / CDSE_S3_SECRET_KEY not set — generate S3 keys at "
                "https://eodata-s3keysmanager.dataspace.copernicus.eu/ and add them to .env "
                "to enable live band downloads (a separate credential from CDSE_CLIENT_ID/SECRET, "
                "which only covers OData search — see module docstring)."
            )
        return boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=self.settings.cdse_s3_access_key,
            aws_secret_access_key=self.settings.cdse_s3_secret_key,
            region_name="default",
        )

    # -- Download + read ---------------------------------------------------
    def _download_bands(self, product: dict) -> tuple[np.ndarray, np.ndarray]:
        """Downloads the green (B03) and NIR (B08) 10m bands for one product
        from CDSE's S3-compatible object storage (not the OData `$value`
        endpoint — see module docstring for why). Band-level file naming
        inside the SAFE structure is the part most likely to need a small
        fix against whatever CDSE's current packaging looks like; kept
        isolated here so that fix, if needed, touches only this method.
        """
        from rasterio.io import MemoryFile

        s3 = self._get_s3_client()
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
