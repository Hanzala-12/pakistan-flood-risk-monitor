"""Shared Copernicus Data Space Ecosystem (CDSE) auth + S3 access, used by
both satellite_copernicus.py (Sentinel-2 optical) and satellite_sentinel1.py
(Sentinel-1 SAR radar) — the two credential types and their quirks are
identical for both missions since they're the same CDSE account. Factored
out here rather than duplicated: unlike hydrology_openmeteo.py's baseline
fetches (deliberately duplicated — see that module's docstring, a case of
similar-shaped-but-distinct computations), this is genuinely the same
auth/download mechanics reused verbatim, and it's credential-handling code
specifically, worth keeping in one place.

See satellite_copernicus.py's module docstring for the full story on why
there are two separate credential types (Sentinel Hub OAuth for search,
S3 keys for downloads) — verified against the live API, not assumed.
"""
import datetime

import boto3

from app.config import get_settings

IDENTITY_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ODATA_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
S3_ENDPOINT_URL = "https://eodata.dataspace.copernicus.eu"
S3_BUCKET = "eodata"
REQUEST_TIMEOUT_S = 30


class CredentialsNotConfigured(RuntimeError):
    pass


class NoUsableSceneFound(RuntimeError):
    pass


class CDSEAuth:
    """One instance per satellite provider (each keeps its own token cache;
    tokens are cheap to fetch and this avoids any cross-provider state)."""

    def __init__(self):
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires_at: datetime.datetime | None = None

    def get_token(self) -> str:
        import requests

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

    def get_s3_client(self):
        if not self.settings.cdse_s3_access_key or not self.settings.cdse_s3_secret_key:
            raise CredentialsNotConfigured(
                "CDSE_S3_ACCESS_KEY / CDSE_S3_SECRET_KEY not set — generate S3 keys at "
                "https://eodata-s3keysmanager.dataspace.copernicus.eu/ and add them to .env "
                "to enable live band downloads (a separate credential from CDSE_CLIENT_ID/SECRET, "
                "which only covers OData search)."
            )
        return boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=self.settings.cdse_s3_access_key,
            aws_secret_access_key=self.settings.cdse_s3_secret_key,
            region_name="default",
        )

    def search_latest_products(
        self, collection: str, extra_filter: str, bbox: tuple[float, float, float, float],
        lookback_days: int, top: int = 5,
    ) -> list[dict]:
        """Generic OData search shared by both missions, returning up to
        `top` candidates newest-first. `extra_filter` is collection-specific
        (e.g. the productType clause), ANDed onto the common
        footprint/date/collection filter.

        Plural on purpose: a single Sentinel-1 IW swath can partially miss a
        district near its edge even though the footprint technically
        intersects the bbox (verified live — see satellite_sentinel1.py's
        coverage check), so that caller needs more than just "the newest
        match" to fall back through. Sentinel-2 currently only uses the
        first result (its per-tile coverage issue is different in kind), but
        both go through the same search method rather than duplicating it."""
        import requests

        token = self.get_token()
        min_lon, min_lat, max_lon, max_lat = bbox
        polygon_wkt = (
            f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},{max_lon} {max_lat},"
            f"{min_lon} {max_lat},{min_lon} {min_lat}))"
        )
        since = (datetime.date.today() - datetime.timedelta(days=lookback_days)).isoformat()
        odata_filter = (
            f"Collection/Name eq '{collection}' and "
            f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon_wkt}') and "
            f"ContentDate/Start gt {since}T00:00:00.000Z and "
            f"{extra_filter}"
        )
        resp = requests.get(
            ODATA_SEARCH_URL,
            params={"$filter": odata_filter, "$orderby": "ContentDate/Start desc", "$top": top},
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        results = resp.json().get("value", [])
        if not results:
            raise NoUsableSceneFound(f"no {collection} scene found in the last {lookback_days} days")

        return [
            {
                "id": r["Id"],
                "name": r["Name"],
                "s3_path": r["S3Path"],
                "observed_at": datetime.datetime.fromisoformat(r["ContentDate"]["Start"].replace("Z", "+00:00")),
            }
            for r in results
        ]

    def search_latest_product(
        self, collection: str, extra_filter: str, bbox: tuple[float, float, float, float], lookback_days: int
    ) -> dict:
        """Convenience wrapper for callers that only ever want the single
        newest match (Sentinel-2 optical — see search_latest_products)."""
        return self.search_latest_products(collection, extra_filter, bbox, lookback_days, top=1)[0]
