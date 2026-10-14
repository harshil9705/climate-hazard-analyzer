"""Application settings, loaded from environment variables (or a local .env file)."""

from datetime import date, timedelta
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ERA5 on Open-Meteo starts in 1940.
MIN_YEAR = 1940
# ERA5 is published with a ~5 day delay; keep a safety margin before treating a year as complete.
ERA5_LAG_DAYS = 10
# Bump whenever detection / trend logic changes so cached analyses are recomputed.
ALGORITHM_VERSION = "1.0.0"


def last_complete_year(today: date | None = None) -> int:
    today = today or date.today()
    return (today - timedelta(days=ERA5_LAG_DAYS)).year - 1


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Climate Hazard Trend Analyzer API"
    environment: str = "development"
    log_level: str = "INFO"

    # Empty URI -> in-memory repository (handy for local dev and tests).
    mongodb_uri: str = ""
    mongodb_db: str = "climate_hazards"
    analysis_ttl_days: int = 30

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    # Pin a single reanalysis model so the record is homogeneous over time
    # (Open-Meteo's default "best_match" blends models with different resolutions).
    open_meteo_model: str = "era5"
    # Optional commercial key (switches to customer-archive-api.open-meteo.com).
    open_meteo_api_key: str = ""
    http_timeout_s: float = 60.0
    upstream_max_retries: int = 3
    upstream_concurrency: int = 2
    # Free tier allows ~600 weighted calls per minute; stay below it.
    upstream_weight_per_minute: float = 500.0

    # Per-client limits (requests per minute).
    rate_limit_per_minute: int = 60
    analysis_rate_limit_per_minute: int = 6
    # Only enable behind a trusted reverse proxy (Render, Cloud Run, ...).
    trust_proxy_headers: bool = False

    max_bbox_span_deg: float = 5.0
    max_grid_points_per_axis: int = 2
    max_request_body_bytes: int = 16_384

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
