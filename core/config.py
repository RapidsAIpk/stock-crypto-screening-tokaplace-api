# core/config.py
import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

try:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict

    PYDANTIC_V2 = True
except ImportError:
    from pydantic import BaseSettings, Field, validator

    PYDANTIC_V2 = False

    class SettingsConfigDict(dict):
        pass

    def field_validator(*fields, mode="after", **kwargs):
        pre = mode == "before"

        def decorator(func):
            target = func.__func__ if isinstance(func, classmethod) else func
            return validator(*fields, pre=pre, allow_reuse=True)(target)

        return decorator

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)
# Massive paid plans allow unlimited API calls, but their guidance is to stay
# below 100 requests/second to avoid throttling. These defaults aim for fast
# response times while leaving healthy headroom for retries and background work.
DEFAULT_MARKET_DATA_REQUESTS_PER_SECOND = 60
DEFAULT_MARKET_DATA_FETCH_CONCURRENCY = 36
DEFAULT_MARKET_DATA_BATCH_SIZE = 1000
DEFAULT_MARKET_DATA_WORKER_POLL_INTERVAL = 5
DEFAULT_BINANCE_FETCH_CONCURRENCY = 20
DEFAULT_BINANCE_REQUESTS_PER_SECOND = 20
# Massive Currencies Starter includes real-time crypto data and unlimited API
# calls, so the backend should not apply the legacy crypto RPM throttle by
# default. Keep the override knob for deployments that still want it.
DEFAULT_MARKET_DATA_CRYPTO_REQUESTS_PER_MINUTE = 0

MARKET_DATA_PROVIDER_ALIASES = {
    "massive": "massive",
    "massive.com": "massive",
    "polygon": "massive",
    "polygonio": "massive",
    "polygon.io": "massive",
    "binance": "binance",
    "binance_spot": "binance",
}


def normalize_market_data_provider(value, default="massive"):
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if not normalized:
        return default

    return MARKET_DATA_PROVIDER_ALIASES.get(normalized, normalized)


class Settings(BaseSettings):
    if PYDANTIC_V2:
        model_config = SettingsConfigDict(
            env_file=str(ENV_FILE),
            extra="ignore",
            case_sensitive=False,
        )

    else:
        class Config:
            env_file = str(ENV_FILE)
            extra = "ignore"
            case_sensitive = False

    APP_NAME: str = "Private Stock & Crypto Screening System"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Plain str, not List[str]: pydantic-settings attempts a json.loads() on any
    # List-typed field's raw env value before validators run, which crashes on a
    # plain comma-separated origin list (not valid JSON). Parsing happens instead
    # in the cors_allow_origins property below.
    CORS_ALLOW_ORIGINS: str = ""
    CORS_ALLOW_CREDENTIALS: bool = False

    MARKET_DATA_WORKER_ENABLED: bool = True
    MARKET_DATA_WORKER_SEED_UNIVERSE: bool = True
    MARKET_DATA_WORKER_POLL_INTERVAL: int = DEFAULT_MARKET_DATA_WORKER_POLL_INTERVAL
    MARKET_DATA_WORKER_BATCH_SIZE: int = DEFAULT_MARKET_DATA_BATCH_SIZE
    MARKET_DATA_FETCH_BATCH_SIZE: int = DEFAULT_MARKET_DATA_BATCH_SIZE
    MASSIVE_FETCH_CONCURRENCY: Optional[int] = None
    POLYGON_FETCH_CONCURRENCY: int = DEFAULT_MARKET_DATA_FETCH_CONCURRENCY
    BINANCE_FETCH_CONCURRENCY: int = DEFAULT_BINANCE_FETCH_CONCURRENCY
    MASSIVE_HTTP2: Optional[bool] = None
    POLYGON_HTTP2: Optional[bool] = None
    MASSIVE_REQUESTS_PER_SECOND: Optional[int] = None
    POLYGON_REQUESTS_PER_SECOND: Optional[int] = None
    BINANCE_REQUESTS_PER_SECOND: int = DEFAULT_BINANCE_REQUESTS_PER_SECOND
    MASSIVE_CRYPTO_REQUESTS_PER_MINUTE: Optional[int] = None
    MASSIVE_CRYPTO_END_OF_DAY_ONLY: bool = False
    CANDLES_PROVIDER: str = "massive"
    CRYPTO_CANDLES_PROVIDER: str = "massive"
    MANUAL_SYMBOLS_MAX: int = 0

    GATE_SESSION_TTL_SECONDS: int = 15 * 60
    SCREENING_MAX_SYMBOLS: int = 0

    MASSIVE_API_KEY: Optional[str] = None
    POLYGON_API_KEY: Optional[str] = None
    ADMIN_API_TOKEN: Optional[str] = None

    ZOYA_ENDPOINT: str = "https://api.zoya.finance/graphql"
    MARKET_DATA_PROVIDER_DOCS_URL: str = "https://massive.com/docs"
    MARKET_DATA_API_BASE_URL: str = "https://api.massive.com"
    BINANCE_PROVIDER_DOCS_URL: str = "https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints"
    BINANCE_API_BASE_URL: str = "https://api.binance.com"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True

            if normalized in {"0", "false", "no", "off", "release", "production"}:
                return False

        return value

    @field_validator("CANDLES_PROVIDER", mode="before")
    @classmethod
    def parse_candles_provider(cls, value):
        normalized = normalize_market_data_provider(value)

        if normalized != "massive":
            return "massive"

        return normalized

    @field_validator("CRYPTO_CANDLES_PROVIDER", mode="before")
    @classmethod
    def parse_crypto_candles_provider(cls, value):
        normalized = normalize_market_data_provider(value)

        if normalized not in {"massive", "binance"}:
            return "massive"

        return normalized

    @field_validator(
        "MARKET_DATA_WORKER_POLL_INTERVAL",
        "MARKET_DATA_WORKER_BATCH_SIZE",
        "MARKET_DATA_FETCH_BATCH_SIZE",
        "MASSIVE_FETCH_CONCURRENCY",
        "POLYGON_FETCH_CONCURRENCY",
        "BINANCE_FETCH_CONCURRENCY",
        mode="before",
    )
    @classmethod
    def parse_positive_ints(cls, value):
        try:
            parsed = int(value)
        except Exception:
            return value
        return max(1, parsed)

    @field_validator(
        "MASSIVE_REQUESTS_PER_SECOND",
        "POLYGON_REQUESTS_PER_SECOND",
        "BINANCE_REQUESTS_PER_SECOND",
        "MASSIVE_CRYPTO_REQUESTS_PER_MINUTE",
        "MANUAL_SYMBOLS_MAX",
        "SCREENING_MAX_SYMBOLS",
        mode="before",
    )
    @classmethod
    def parse_non_negative_ints(cls, value):
        try:
            parsed = int(value)
        except Exception:
            return value
        return max(0, parsed)

    @property
    def cors_allow_origins(self) -> List[str]:
        raw = (self.CORS_ALLOW_ORIGINS or "").strip()

        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                origins = [str(item).strip() for item in parsed if str(item).strip()]
            except (ValueError, TypeError):
                origins = []
        else:
            origins = [item.strip() for item in raw.split(",") if item.strip()]

        if self.APP_ENV.lower() == "production":
            return origins

        return origins or [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "https://screener-123.netlify.app",
            "https://tokaplace.com",
            "https://www.tokaplace.com",
        ]

    @property
    def market_data_fetch_concurrency(self) -> int:
        if self.MASSIVE_FETCH_CONCURRENCY is not None:
            return max(1, int(self.MASSIVE_FETCH_CONCURRENCY))
        return max(1, int(self.POLYGON_FETCH_CONCURRENCY or 1))

    @property
    def market_data_http2_enabled(self) -> bool:
        if self.MASSIVE_HTTP2 is not None:
            return bool(self.MASSIVE_HTTP2)
        if self.POLYGON_HTTP2 is not None:
            return bool(self.POLYGON_HTTP2)
        return True

    @property
    def market_data_requests_per_second(self) -> int:
        if self.MASSIVE_REQUESTS_PER_SECOND is not None:
            return max(0, int(self.MASSIVE_REQUESTS_PER_SECOND))
        if self.POLYGON_REQUESTS_PER_SECOND is not None:
            return max(0, int(self.POLYGON_REQUESTS_PER_SECOND))
        return DEFAULT_MARKET_DATA_REQUESTS_PER_SECOND

    @property
    def market_data_crypto_requests_per_minute(self) -> int:
        if self.MASSIVE_CRYPTO_REQUESTS_PER_MINUTE is not None:
            return max(0, int(self.MASSIVE_CRYPTO_REQUESTS_PER_MINUTE))
        return DEFAULT_MARKET_DATA_CRYPTO_REQUESTS_PER_MINUTE

    @property
    def market_data_api_key(self) -> Optional[str]:
        key = str(self.MASSIVE_API_KEY or self.POLYGON_API_KEY or "").strip()
        return key or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
