import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_current_scan_id: ContextVar[str | None] = ContextVar("scan_progress_scan_id", default=None)


class ScanProgressBroadcaster:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, scan_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(scan_id, set()).add(websocket)

    async def unsubscribe(self, scan_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(scan_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(scan_id, None)

    async def emit(self, scan_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(scan_id, set()))

        if not connections:
            return

        message = {
            "type": "progress",
            "scan_id": scan_id,
            "timestamp": int(time.time() * 1000),
            **payload,
        }

        stale: list[tuple[str, WebSocket]] = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append((scan_id, websocket))

        for scan_key, websocket in stale:
            await self.unsubscribe(scan_key, websocket)


broadcaster = ScanProgressBroadcaster()


def current_scan_id() -> str | None:
    return _current_scan_id.get()


async def emit_scan_progress(
    stage: str,
    message: str,
    *,
    symbol: str | None = None,
    current: int | None = None,
    total: int | None = None,
    detail: str | None = None,
    scan_id: str | None = None,
) -> None:
    active_scan_id = scan_id or current_scan_id()
    if not active_scan_id:
        return

    payload: dict[str, Any] = {
        "stage": stage,
        "message": message,
    }
    if symbol is not None:
        payload["symbol"] = symbol
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if detail is not None:
        payload["detail"] = detail

    await broadcaster.emit(active_scan_id, payload)


def schedule_scan_progress(
    stage: str,
    message: str,
    *,
    symbol: str | None = None,
    current: int | None = None,
    total: int | None = None,
    detail: str | None = None,
    scan_id: str | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(
        emit_scan_progress(
            stage,
            message,
            symbol=symbol,
            current=current,
            total=total,
            detail=detail,
            scan_id=scan_id,
        )
    )


@asynccontextmanager
async def scan_progress_scope(scan_id: str | None):
    token = _current_scan_id.set((scan_id or "").strip() or None)
    try:
        if current_scan_id():
            await emit_scan_progress("started", "Scan started")
        yield
        if current_scan_id():
            await emit_scan_progress("completed", "Scan completed")
    finally:
        _current_scan_id.reset(token)
