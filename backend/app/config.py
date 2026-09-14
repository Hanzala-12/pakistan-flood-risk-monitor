"""
Central settings for the backend. Everything that differs between a
"runs today with zero credentials" demo and a fully live deployment is a
setting here, not a code branch scattered through the ingestion modules.

Load order: environment variables > .env file in the repo root > defaults
below. Copy config/settings.example.env to .env and fill in what you have;
anything you leave out just keeps running in its documented fallback mode.
"""
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage -------------------------------------------------------
    database_url: str = f"sqlite:///{(REPO_ROOT / 'data' / 'flood_risk.db').as_posix()}"
    districts_geojson_path: Path = REPO_ROOT / "config" / "districts.geojson"

    # --- Satellite signal ------------------------------------------------
    # "mock"       -> synthetic-but-labeled water anomaly, no network/creds needed.
    # "copernicus" -> real Sentinel-2 fetch from Copernicus Data Space Ecosystem +
    #                 NDWI / trained-model inference. Needs cdse_client_id/secret below.
    satellite_provider: str = "mock"
    cdse_client_id: str | None = None
    cdse_client_secret: str | None = None
    # Separate from cdse_client_id/secret above: those are a Sentinel Hub OAuth
    # client (client_credentials), which authenticates OData *search* fine but
    # is the wrong audience for downloading product bytes (CDSE returns 401
    # "Token audience not allowed" / DAT-ZIP-609 if you try). Verified against
    # the live API while building this, not assumed from docs. Band downloads
    # go through CDSE's S3-compatible object storage instead, which is also
    # the method CDSE's own docs recommend for full-dataset downloads. Create
    # these at https://eodata-s3keysmanager.dataspace.copernicus.eu/.
    cdse_s3_access_key: str | None = None
    cdse_s3_secret_key: str | None = None
    satellite_lookback_days: int = 10       # how far back to search for a usable scene
    satellite_max_cloud_cover: float = 40.0  # percent

    # --- Rainfall signal -------------------------------------------------
    # Open-Meteo's archive+forecast APIs are free and need no API key, so this
    # is real by default (unlike the satellite/model signal). See
    # app/ingestion/rainfall_openmeteo.py for why this replaces the plan's
    # NASA GPM / Earth Engine suggestion.
    rainfall_provider: str = "open_meteo"
    rainfall_baseline_years: int = 5

    # --- Segmentation model (see ../../files/flood_segmentation_training.ipynb) ---
    model_weights_path: Path = REPO_ROOT / "models" / "flood_segmentation_model.pt"
    model_config_path: Path = REPO_ROOT / "models" / "model_config.json"

    # --- Fusion weights (IMPLEMENTATION_PLAN.md section 6.4) -------------
    # Rebalanced from the original 3-term (0.34/0.33/0.33) split when two more real
    # signals were added (soil moisture, river discharge — found by researching other
    # open-source flood-risk projects, see README "Data sourcing decisions"). Still a
    # documented heuristic, not fitted to any outcome data — same honesty caveat as the
    # original three. River discharge gets the same top weight as water_anomaly since
    # it's the most direct, dynamic flood indicator now in the system (actual water
    # currently in the channel); terrain and soil moisture are the two slower-changing,
    # more baseline-like factors, weighted lower accordingly.
    fusion_weight_water: float = 0.25
    fusion_weight_rainfall: float = 0.20
    fusion_weight_terrain: float = 0.15
    fusion_weight_soil_moisture: float = 0.15
    fusion_weight_river_discharge: float = 0.25

    # --- Scheduler ---------------------------------------------------------
    scheduler_enabled: bool = True
    refresh_hour_utc: int = 2  # daily job fire time

    # --- Alerting (app/alerting/ntfy.py) ------------------------------------
    # ntfy.sh: open-source pub-sub push notifications over a plain HTTP POST,
    # no account needed on the free public instance (or self-host your own —
    # same protocol). Off by default since it needs a topic name you pick
    # yourself (topics on the public instance are unauthenticated by name,
    # so pick something unguessable, not e.g. "flood-alerts").
    ntfy_enabled: bool = False
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None

    # --- API -----------------------------------------------------------
    cors_allow_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
