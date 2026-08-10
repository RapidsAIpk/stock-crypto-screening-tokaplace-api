import asyncio
import logging

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}


def register(scan_id: str, task: asyncio.Task) -> None:
    if not scan_id:
        return
    _tasks[scan_id] = task


def unregister(scan_id: str) -> None:
    if not scan_id:
        return
    _tasks.pop(scan_id, None)


def cancel(scan_id: str) -> bool:
    task = _tasks.get(scan_id)
    if task is None or task.done():
        return False
    task.cancel()
    logger.info("Scan %s cancelled by request", scan_id)
    return True
