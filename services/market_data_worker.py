import asyncio
import logging
import time

from core.config import settings
from services.asset_router import load_crypto_universe, load_zoya_universe, normalize_crypto_symbol
from services.market_data import (
    DEFAULT_BATCH_SIZE,
    FAILED_REFRESH_BACKOFF_SECONDS,
    WORKER_CACHE_TIMEFRAMES,
    active_candle_provider,
    active_crypto_candle_provider,
    fetch_batches,
    is_payload_for_symbol_provider,
    is_refresh_due,
    next_refresh_at_for_timeframe,
    timeframe_seconds,
    timeframe_uses_worker_cache,
)
from services.market_data_store import store


logger = logging.getLogger(__name__)
WORKER_TIMEFRAMES = tuple(sorted(WORKER_CACHE_TIMEFRAMES, key=timeframe_seconds))
SYMBOL_SEED_INTERVAL_SECONDS = 5 * 60


class MarketDataWorker:
    def __init__(self, poll_interval: int = 15, batch_size: int = DEFAULT_BATCH_SIZE):
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._task = None
        self._running = False
        self._started_at = None
        self._last_run_at = None
        self._last_success_at = None
        self._last_error = None
        self._last_seed_at = None

    async def start(self):
        if self._task:
            return

        self._running = True
        self._started_at = int(time.time())
        self._last_error = None
        if settings.MARKET_DATA_WORKER_SEED_UNIVERSE:
            self._seed_symbol_interest(force=True)
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Market data worker started poll_interval=%s batch_size=%s candles_provider=%s seed_universe=%s",
            self.poll_interval,
            self.batch_size,
            active_candle_provider(),
            settings.MARKET_DATA_WORKER_SEED_UNIVERSE,
        )

    async def stop(self):
        self._running = False

        if not self._task:
            return

        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        logger.info("Market data worker stopped")

    def update_runtime(self, poll_interval=None, batch_size=None):
        if poll_interval is not None:
            self.poll_interval = max(1, int(poll_interval))

        if batch_size is not None:
            self.batch_size = max(1, int(batch_size))

    async def refresh_once(self):
        self._last_run_at = int(time.time())

        try:
            if settings.MARKET_DATA_WORKER_SEED_UNIVERSE:
                await asyncio.to_thread(self._seed_symbol_interest, force=True)
            await self.refresh_due_symbols()
            await asyncio.to_thread(store.prune)
            self._last_success_at = int(time.time())
            self._last_error = None
        except Exception:
            self._last_error = "market data refresh failed"
            logger.exception("Market data worker manual refresh failed")
            raise

    async def _run(self):
        while self._running:
            self._last_run_at = int(time.time())
            try:
                if settings.MARKET_DATA_WORKER_SEED_UNIVERSE:
                    await asyncio.to_thread(self._seed_symbol_interest)
                await self.refresh_due_symbols()
                await asyncio.to_thread(store.prune)
                self._last_success_at = int(time.time())
                self._last_error = None
            except Exception:
                self._last_error = "market data refresh failed"
                logger.exception("Market data worker loop failed")
                await asyncio.sleep(self.poll_interval)
                continue

            await asyncio.sleep(self.poll_interval)

    def _universe_symbols(self):
        stock_symbols = [
            item["symbol"]
            for item in load_zoya_universe()
            if item.get("symbol")
        ]
        crypto_symbols = []
        for item in load_crypto_universe():
            symbol = normalize_crypto_symbol(item.get("symbol"))
            if symbol:
                crypto_symbols.append(symbol)

        symbols = list(dict.fromkeys([*stock_symbols, *crypto_symbols]))
        max_symbols = int(settings.SCREENING_MAX_SYMBOLS or 0)

        if max_symbols > 0:
            return symbols[:max_symbols]

        return symbols

    def _seed_symbol_interest(self, force: bool = False):
        now = int(time.time())

        if (
            not force
            and self._last_seed_at is not None
            and (now - self._last_seed_at) < SYMBOL_SEED_INTERVAL_SECONDS
        ):
            return

        symbols = self._universe_symbols()
        if not symbols:
            self._last_seed_at = now
            return

        tracked_symbols = 0
        for timeframe in WORKER_TIMEFRAMES:
            cached_map = store.get_cached(symbols, timeframe)
            next_refresh_map = {}

            for symbol in symbols:
                cached = cached_map.get(symbol)
                if not cached:
                    next_refresh_map[symbol] = now
                    continue

                payload = cached["payload"] or {}
                if not is_payload_for_symbol_provider(payload, symbol):
                    next_refresh_map[symbol] = now
                    continue

                cached_candles = payload.get("candles") or []
                if not cached_candles:
                    next_refresh_map[symbol] = now
                    continue

                next_refresh_map[symbol] = (
                    now
                    if is_refresh_due(payload, timeframe, now)
                    else int(
                        payload.get(
                            "next_refresh_at",
                            next_refresh_at_for_timeframe(timeframe, now),
                        )
                    )
                )

            if next_refresh_map:
                tracked_symbols += len(next_refresh_map)
                store.register_interest(
                    list(next_refresh_map.keys()),
                    timeframe,
                    next_refresh_map=next_refresh_map,
                )

        self._last_seed_at = now
        logger.info(
            "Seeded market-data interest universe_symbols=%s tracked_symbols=%s timeframes=%s",
            len(symbols),
            tracked_symbols,
            len(WORKER_TIMEFRAMES),
        )

    async def refresh_due_symbols(self):
        due = await asyncio.to_thread(store.due_symbols, limit=max(1, int(self.batch_size)))
        now = int(time.time())
        skipped_short = [
            timeframe
            for timeframe in due.keys()
            if not timeframe_uses_worker_cache(timeframe)
        ]
        if skipped_short:
            logger.info(
                "Worker skipping unmanaged timeframes=%s",
                sorted(skipped_short),
            )
            await asyncio.to_thread(store.clear_interest_for_timeframes, skipped_short)
        ordered_timeframes = [
            timeframe
            for timeframe in WORKER_TIMEFRAMES
            if timeframe_uses_worker_cache(timeframe) and due.get(timeframe)
        ]

        for timeframe in ordered_timeframes:
            symbols = due.get(timeframe) or []
            if not symbols:
                continue
            cached_map = await asyncio.to_thread(store.get_cached, symbols, timeframe)
            refresh_symbols = []
            reschedule_map = {}

            for symbol in symbols:
                cached = cached_map.get(symbol)
                if not cached:
                    refresh_symbols.append(symbol)
                    continue

                payload = cached["payload"] or {}
                if not is_payload_for_symbol_provider(payload, symbol):
                    refresh_symbols.append(symbol)
                    continue

                cached_candles = payload.get("candles") or []
                if not cached_candles:
                    refresh_symbols.append(symbol)
                    continue

                if is_refresh_due(payload, timeframe, now):
                    refresh_symbols.append(symbol)
                    continue

                reschedule_map[symbol] = int(
                    payload.get(
                        "next_refresh_at",
                        next_refresh_at_for_timeframe(timeframe, now),
                    )
                )

            if reschedule_map:
                await asyncio.to_thread(
                    store.update_interest_schedule,
                    list(reschedule_map.keys()),
                    timeframe,
                    reschedule_map,
                )

            if not refresh_symbols:
                continue

            items = await fetch_batches(
                refresh_symbols,
                timeframe,
                batch_size=self.batch_size
            )

            if items:
                await asyncio.to_thread(store.store_snapshots, items, timeframe)

            resolved_symbols = {
                item.get("symbol")
                for item in items or []
                if item.get("symbol")
            }
            unresolved_symbols = [
                symbol for symbol in refresh_symbols
                if symbol not in resolved_symbols
            ]
            if unresolved_symbols:
                backoff_until = now + max(
                    FAILED_REFRESH_BACKOFF_SECONDS,
                    timeframe_seconds(timeframe) // 4,
                )
                await asyncio.to_thread(
                    store.update_interest_schedule,
                    unresolved_symbols,
                    timeframe,
                    {
                        symbol: backoff_until
                        for symbol in unresolved_symbols
                    },
                )

    def status(self):
        return {
            "running": self._running and self._task is not None,
            "poll_interval": self.poll_interval,
            "batch_size": self.batch_size,
            "candles_provider": active_candle_provider(),
            "crypto_candles_provider": active_crypto_candle_provider(),
            "seed_universe": settings.MARKET_DATA_WORKER_SEED_UNIVERSE,
            "started_at": self._started_at,
            "last_run_at": self._last_run_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
        }
