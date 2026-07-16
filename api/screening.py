# api/screening.py
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from models.filters import ScreeningRequest
from models.results import (
    CryptoExchangeOptionsResponse,
    ScreeningDetailResponse,
    ScreeningResponse,
    StockFilterOptionsResponse,
)
from services.screener import get_asset_detail, run_single, run_gate, run_entry
from services.indicators import unsupported_indicator_names
from services.integration_runtime import integration_runtime
from services.market_data import active_candle_provider, active_crypto_candle_provider
from services.asset_router import list_crypto_exchanges
from services.stock_reference import list_stock_filter_options
from core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


class WorkerConfigRequest(BaseModel):
    poll_interval: int | None = None
    batch_size: int | None = None


class IntegrationProviderConfig(BaseModel):
    enabled: bool | None = None
    paused: bool | None = None
    api_key: str | None = None
    call_limit: int | None = None


class IntegrationConfigRequest(BaseModel):
    providers: dict[str, IntegrationProviderConfig] = Field(default_factory=dict)


class DetailRequest(BaseModel):
    symbol: str
    asset_type: str
    timeframe: str
    scan_stage: str = "single"
    request: ScreeningRequest


def _require_supported_indicators(request: ScreeningRequest):
    unsupported = unsupported_indicator_names(request.indicators)
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported indicator(s): {', '.join(unsupported)}.",
        )


def _require_admin(http_request: Request):
    expected = (settings.ADMIN_API_TOKEN or "").strip()

    if not expected:
        if settings.APP_ENV.lower() == "production":
            raise HTTPException(status_code=403, detail="Admin token required.")
        return

    provided = (http_request.headers.get("X-Admin-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="Admin token required.")


# --------------------------------------------
# SINGLE TIMEFRAME
# --------------------------------------------
@router.post("/run", response_model=ScreeningResponse)
async def run_screening(request: ScreeningRequest):
    started = time.perf_counter()

    if request.timeframe_mode != "single":
        raise HTTPException(
            status_code=400,
            detail="Use /run-gate and /run-entry for two-timeframe mode."
        )
    _require_supported_indicators(request)

    response = await run_single(request)
    logger.info(
        "API /screen/run timeframe=%s results=%s elapsed=%.2fs",
        request.single_timeframe,
        len(response.get("results", [])),
        time.perf_counter() - started,
    )
    return response


@router.get("/crypto-exchanges", response_model=CryptoExchangeOptionsResponse)
async def crypto_exchange_options():
    return {"exchanges": list_crypto_exchanges()}


@router.get("/stock-filter-options", response_model=StockFilterOptionsResponse)
async def stock_filter_options():
    options = list_stock_filter_options()
    return {
        "asset_categories": options.get("asset_categories") or [],
        "sectors": options.get("sectors") or [],
    }


@router.post("/details", response_model=ScreeningDetailResponse)
async def screening_details(body: DetailRequest):
    detail = await get_asset_detail(
        symbol=body.symbol,
        asset_type=body.asset_type,
        timeframe=body.timeframe,
        request=body.request,
        scan_stage=body.scan_stage,
    )

    if detail is None:
        raise HTTPException(status_code=404, detail="Asset detail unavailable.")

    return {"detail": detail}


# --------------------------------------------
# GATE TIMEFRAME
# --------------------------------------------
def _client_identity(http_request: Request):
    return (
        http_request.headers.get("X-Client-Id")
        or http_request.headers.get("X-User-Id")
        or getattr(http_request.client, "host", None)
    )


def _worker_from_request(http_request: Request):
    worker = getattr(http_request.app.state, "market_data_worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="Market data worker unavailable.")
    return worker


def _provider_docs_url(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if normalized == "binance":
        return settings.BINANCE_PROVIDER_DOCS_URL
    return settings.MARKET_DATA_PROVIDER_DOCS_URL


def _provider_base_url(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if normalized == "binance":
        return settings.BINANCE_API_BASE_URL
    return settings.MARKET_DATA_API_BASE_URL


@router.get("/ops/worker")
async def worker_status(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    return {
        "worker": worker.status(),
        "worker_enabled_by_config": settings.MARKET_DATA_WORKER_ENABLED,
    }


@router.get("/ops/runtime-settings")
async def runtime_settings(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    stock_provider = active_candle_provider()
    crypto_provider = active_crypto_candle_provider()

    return {
        "app": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "env": settings.APP_ENV,
            "debug": settings.DEBUG,
            "log_level": settings.LOG_LEVEL,
        },
        "server": {
            "host": settings.HOST,
            "port": settings.PORT,
            "cors_allow_origins": settings.cors_allow_origins,
            "cors_allow_credentials": settings.CORS_ALLOW_CREDENTIALS,
        },
        "screening": {
            "screening_max_symbols": settings.SCREENING_MAX_SYMBOLS,
            "manual_symbols_max": settings.MANUAL_SYMBOLS_MAX,
            "gate_session_ttl_seconds": settings.GATE_SESSION_TTL_SECONDS,
            "candles_provider": stock_provider,
            "crypto_candles_provider": crypto_provider,
            "provider_docs_url": _provider_docs_url(stock_provider),
            "crypto_provider_docs_url": _provider_docs_url(crypto_provider),
            "api_base_url": _provider_base_url(stock_provider),
            "crypto_api_base_url": _provider_base_url(crypto_provider),
        },
        "worker": {
            "enabled_by_config": settings.MARKET_DATA_WORKER_ENABLED,
            "seed_universe": settings.MARKET_DATA_WORKER_SEED_UNIVERSE,
            "effective": worker.status(),
            "configured_poll_interval": settings.MARKET_DATA_WORKER_POLL_INTERVAL,
            "configured_batch_size": settings.MARKET_DATA_WORKER_BATCH_SIZE,
            "fetch_batch_size": settings.MARKET_DATA_FETCH_BATCH_SIZE,
            "massive_fetch_concurrency": settings.market_data_fetch_concurrency,
            "massive_requests_per_second": settings.market_data_requests_per_second,
            "massive_crypto_requests_per_minute": settings.market_data_crypto_requests_per_minute,
            "massive_crypto_end_of_day_only": settings.MASSIVE_CRYPTO_END_OF_DAY_ONLY,
            "binance_fetch_concurrency": settings.BINANCE_FETCH_CONCURRENCY,
            "binance_requests_per_second": settings.BINANCE_REQUESTS_PER_SECOND,
        },
        "integrations": {
            **integration_runtime.snapshot(),
            "admin_api_token_required": bool((settings.ADMIN_API_TOKEN or "").strip()),
        },
    }

@router.get("/ops/integrations")
async def integrations_status(http_request: Request):
    _require_admin(http_request)
    return integration_runtime.snapshot()


@router.post("/ops/integrations/config")
async def integrations_config(body: IntegrationConfigRequest, http_request: Request):
    _require_admin(http_request)

    for provider_name, provider_config in body.providers.items():
        integration_runtime.update_provider(
            provider_name,
            enabled=provider_config.enabled,
            paused=provider_config.paused,
            api_key=provider_config.api_key,
            call_limit=provider_config.call_limit,
        )

    return integration_runtime.snapshot()


@router.get("/ops/integrations/{provider}/history")
async def integration_history(provider: str, http_request: Request):
    _require_admin(http_request)
    history = integration_runtime.get_history(provider)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return history


@router.post("/ops/diagnose")
async def ops_diagnose(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    return integration_runtime.diagnose(worker_status=worker.status())


@router.post("/ops/worker/start")
async def worker_start(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    await worker.start()
    return {"worker": worker.status()}


@router.post("/ops/worker/stop")
async def worker_stop(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    await worker.stop()
    return {"worker": worker.status()}


@router.post("/ops/worker/refresh")
async def worker_refresh(http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    await worker.refresh_once()
    return {"worker": worker.status()}


@router.post("/ops/worker/config")
async def worker_config(body: WorkerConfigRequest, http_request: Request):
    _require_admin(http_request)
    worker = _worker_from_request(http_request)
    worker.update_runtime(
        poll_interval=body.poll_interval,
        batch_size=body.batch_size,
    )
    return {"worker": worker.status()}


@router.post("/run-gate", response_model=ScreeningResponse)
async def run_gate_screening(request: ScreeningRequest, http_request: Request):
    started = time.perf_counter()

    if request.timeframe_mode != "gate_entry":
        raise HTTPException(
            status_code=400,
            detail="Gate requires timeframe_mode='gate_entry'."
        )
    _require_supported_indicators(request)

    response = await run_gate(request, client_id=_client_identity(http_request))
    logger.info(
        "API /screen/run-gate timeframe=%s results=%s elapsed=%.2fs",
        request.gate_timeframe,
        len(response.get("results", [])),
        time.perf_counter() - started,
    )
    return response


# --------------------------------------------
# ENTRY TIMEFRAME
# --------------------------------------------
@router.post("/run-entry", response_model=ScreeningResponse)
async def run_entry_screening(request: ScreeningRequest, http_request: Request):
    started = time.perf_counter()

    if request.timeframe_mode != "gate_entry":
        raise HTTPException(
            status_code=400,
            detail="Entry requires timeframe_mode='gate_entry'."
        )

    if not request.gate_session_id:
        raise HTTPException(
            status_code=400,
            detail="Entry requires gate_session_id from /run-gate."
        )
    _require_supported_indicators(request)

    response = await run_entry(request, client_id=_client_identity(http_request))
    logger.info(
        "API /screen/run-entry timeframe=%s results=%s elapsed=%.2fs",
        request.entry_timeframe,
        len(response.get("results", [])),
        time.perf_counter() - started,
    )
    return response
