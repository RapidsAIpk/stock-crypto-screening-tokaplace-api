# services/dev_audit_logger.py
import json
import logging
from pathlib import Path

from core.config import BASE_DIR, settings

logger = logging.getLogger(__name__)

DEV_AUDIT_DIR = BASE_DIR / "logs" / "dev_audit"


def dev_audit_enabled():
    return bool(getattr(settings, "DEV_ENV", False))


def write_dev_market_data_audit(run_id, stage, summary, symbol_payloads):
    """Append a market-data audit snapshot to a per-run JSON file. Dev-mode only.

    Never raises: a failure here must not affect the screening request itself.
    """
    if not dev_audit_enabled():
        return

    try:
        DEV_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        file_path = DEV_AUDIT_DIR / f"{run_id}.json"

        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        else:
            data = {"run_id": run_id, "stages": {}}

        data["stages"][stage] = {
            "summary": summary,
            "symbols": symbol_payloads,
        }

        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, default=str)
    except Exception:
        logger.warning("dev_audit_logger: failed to write dev audit log for run_id=%s stage=%s", run_id, stage, exc_info=True)
