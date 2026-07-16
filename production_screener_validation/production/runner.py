from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

from models.filters import ScreeningRequest
from services import screener

from ..contracts import ScreenerCase
from ..fixture_store import FixtureStore, slice_candles_to_date


def _model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return dict(vars(value))


class ProductionRunner:
    """Run production screening while replacing only external fixture boundaries."""

    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    def _assets(self, case: ScreenerCase) -> list[dict[str, Any]]:
        metadata = self.store.load_metadata(case.fixture_id)
        return [{"symbol": symbol, **deepcopy(metadata.get(symbol, {}))} for symbol in case.symbols]

    def _data(self, case: ScreenerCase, timeframe: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for asset in assets:
            symbol = asset["symbol"]
            candles = slice_candles_to_date(
                self.store.load_candles(case.fixture_id, symbol, timeframe),
                case.evaluation_date,
            )
            latest = candles[-1]
            rows.append({
                **deepcopy(asset),
                "symbol": symbol,
                "price": float(latest["close"]),
                "volume": float(latest["volume"]),
                "candles": deepcopy(candles),
                "channels": {},
                "stickers": [],
                "matched_indicators": [],
            })
        return rows

    async def _run_with_fixtures(self, case: ScreenerCase, request: ScreeningRequest, operation: str, *, client_id: str) -> dict[str, Any]:
        assets = self._assets(case)

        async def build_asset_universe(_request: Any) -> list[dict[str, Any]]:
            return deepcopy(assets)

        async def fetch_screening_data(requested_assets: list[dict[str, Any]], timeframe: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            allowed = {asset["symbol"] for asset in requested_assets}
            return self._data(case, timeframe, [asset for asset in assets if asset["symbol"] in allowed])

        with patch.object(screener, "build_asset_universe", new=build_asset_universe), patch.object(
            screener, "fetch_screening_data", new=fetch_screening_data
        ):
            if operation == "single":
                return await screener.run_single(request)
            if operation == "gate":
                return await screener.run_gate(request, client_id=client_id)
            if operation == "entry":
                return await screener.run_entry(request, client_id=client_id)
        raise ValueError(f"unknown production operation '{operation}'")

    @staticmethod
    def _result_payload(response: Any) -> dict[str, Any]:
        payload = _model_dict(response)
        results = [_model_dict(item) for item in payload.get("results", [])]
        return {
            "symbols": sorted(str(item["symbol"]).upper() for item in results),
            "results": results,
            "gate_session_id": payload.get("gate_session_id"),
        }

    async def run_case(self, case: ScreenerCase) -> dict[str, Any]:
        client_id = f"production-validator:{case.case_id}"
        try:
            if case.timeframe_mode == "single":
                request = ScreeningRequest(**case.production_payload())
                response = await self._run_with_fixtures(case, request, "single", client_id=client_id)
                return {"status": "evaluated", "mode": "single", **self._result_payload(response)}

            gate_request = ScreeningRequest(**case.production_payload())
            gate_response = await self._run_with_fixtures(case, gate_request, "gate", client_id=client_id)
            gate = self._result_payload(gate_response)
            if not gate["gate_session_id"]:
                return {"status": "production_error", "mode": "gate_entry", "error": "production gate returned no session ID", "gate": gate}
            entry_payload = case.production_payload(gate_session_id=gate["gate_session_id"])
            entry_request = ScreeningRequest(**entry_payload)
            entry_response = await self._run_with_fixtures(case, entry_request, "entry", client_id=client_id)
            entry = self._result_payload(entry_response)
            return {"status": "evaluated", "mode": "gate_entry", "symbols": entry["symbols"], "results": entry["results"], "gate": gate, "entry": entry}
        except Exception as exc:
            return {"status": "production_error", "mode": case.timeframe_mode, "symbols": [], "results": [], "error": f"{type(exc).__name__}: {exc}"}
