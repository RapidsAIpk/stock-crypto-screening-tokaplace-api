from contextlib import asynccontextmanager
import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import screening
from core.config import settings
from core.logging_config import configure_logging
from services.market_data import (
    active_candle_provider,
    active_crypto_candle_provider,
    close_market_data_clients,
)
from services.market_data_worker import MarketDataWorker


configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


def _ready_mode_label() -> str:
    stock_provider = active_candle_provider()
    crypto_provider = active_crypto_candle_provider()

    if stock_provider == "massive" and crypto_provider == "massive":
        return "massive_candles"

    return f"stocks={stock_provider},crypto={crypto_provider}"


def _requires_market_data_api_key() -> bool:
    return active_candle_provider() == "massive"


def build_market_data_worker() -> MarketDataWorker:
    return MarketDataWorker(
        poll_interval=settings.MARKET_DATA_WORKER_POLL_INTERVAL,
        batch_size=settings.MARKET_DATA_WORKER_BATCH_SIZE,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = build_market_data_worker()
    app.state.market_data_worker = worker

    if settings.MARKET_DATA_WORKER_ENABLED:
        await worker.start()
    else:
        logger.info("Market data worker is disabled by configuration")

    yield

    await worker.stop()
    await close_market_data_clients()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    allow_origins = settings.cors_allow_origins
    allow_all_origins = "*" in allow_origins
    allow_origin_regex = None

    if settings.APP_ENV.lower() != "production":
        allow_origin_regex = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or [],
        allow_origin_regex=allow_origin_regex,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS and not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        screening.router,
        prefix="/screen",
        tags=["Screening"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/")
    async def root():
        return {
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
        }

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "environment": settings.APP_ENV,
        }

    @app.get("/readyz")
    async def readyz():
        worker_status = app.state.market_data_worker.status()
        payload = {
            "status": "ready",
            "mode": _ready_mode_label(),
            "worker": worker_status,
        }

        if _requires_market_data_api_key() and not settings.market_data_api_key:
            payload["status"] = "degraded"
            return JSONResponse(status_code=503, content=payload)

        if settings.MARKET_DATA_WORKER_ENABLED and not worker_status.get("running"):
            payload["status"] = "degraded"
            return JSONResponse(status_code=503, content=payload)

        return JSONResponse(status_code=200, content=payload)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
