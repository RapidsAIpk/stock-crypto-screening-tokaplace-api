from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..contracts import ScreenerCase, SymbolEvidence
from ..fixture_store import FixtureStore, slice_candles_to_date
from .rule_engine import InsufficientReferenceData, evaluate_custom, evaluate_standard
from .talib_engine import TALIB_VERSION


STANDARD = {"rsi", "aroon", "macd", "ema", "sma", "adx", "stochrsi"}


class ReferenceOracle:
    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    def evaluate_case(self, case: ScreenerCase, *, scope: str = "single") -> dict[str, Any]:
        manifest = self.store.verify(case.fixture_id)
        metadata = self.store.load_metadata(case.fixture_id)
        timeframe = case.single_timeframe if scope == "single" else case.gate_timeframe if scope == "primary" else case.entry_timeframe
        selected = [item for item in case.indicators if item.timeframe == scope]
        evidence: dict[str, Any] = {}
        expected: list[str] = []
        excluded: list[str] = []
        insufficient: list[str] = []
        for symbol in case.symbols:
            try:
                candles = slice_candles_to_date(
                    self.store.load_candles(case.fixture_id, symbol, str(timeframe)),
                    case.evaluation_date,
                )
                symbol_metadata = metadata.get(symbol, {})
                rules: list[dict[str, Any]] = []
                prefilter = self._prefilter(case, candles[-1], symbol_metadata)
                rules.extend(prefilter["rules"])
                passed = prefilter["passed"]
                for item in selected:
                    result = evaluate_standard(item.name, candles, item.config) if item.name in STANDARD else evaluate_custom(item.name, candles, symbol_metadata, item.config)
                    rules.append(result)
                    passed = passed and bool(result["passed"])
                if passed and case.channel_respect:
                    result = self._channel_respect(candles, case.channel_respect)
                    rules.append(result); passed = passed and result["passed"]
                if passed and case.confluence:
                    result = self._confluence(candles, case.confluence)
                    rules.append(result); passed = passed and result["passed"]
                item = SymbolEvidence(symbol, passed, "evaluated", rules, symbol_metadata)
                (expected if passed else excluded).append(symbol)
            except (InsufficientReferenceData, KeyError) as exc:
                insufficient.append(symbol)
                item = SymbolEvidence(symbol, None, "insufficient_data", error=str(exc))
            except Exception as exc:
                item = SymbolEvidence(symbol, None, "reference_error", error=str(exc))
            evidence[symbol] = asdict(item)
        status = "reference_error" if any(item["status"] == "reference_error" for item in evidence.values()) else "insufficient_data" if insufficient else "evaluated"
        return {
            "status": status,
            "case_id": case.case_id,
            "case_checksum": case.checksum,
            "fixture_id": case.fixture_id,
            "fixture_hash": manifest["semantic_hash"],
            "scope": scope,
            "timeframe": timeframe,
            "reference_engine": "TA-Lib plus independent validation oracles",
            "talib_version": TALIB_VERSION,
            "expected_symbols": sorted(expected),
            "excluded_symbols": sorted(excluded),
            "insufficient_data_symbols": sorted(insufficient),
            "symbol_evidence": evidence,
        }

    @staticmethod
    def _prefilter(case: ScreenerCase, latest: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        rules: list[dict[str, Any]] = []; passed = True
        if case.price_range:
            price = float(latest["close"]); minimum = case.price_range.get("min_price"); maximum = case.price_range.get("max_price")
            result = (minimum is None or price >= float(minimum)) and (maximum is None or price <= float(maximum))
            rules.append({"filter": "price_range", "passed": result, "values": {"price": price}}); passed &= result
        if case.compliance_status:
            result = metadata.get("compliance_status") == case.compliance_status
            rules.append({"filter": "compliance_status", "passed": result, "values": {"actual": metadata.get("compliance_status")}}); passed &= result
        return {"passed": passed, "rules": rules}

    @staticmethod
    def _channel_respect(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        from .custom_engine import lrc, regression_channel, trend_channel
        channel_type = config["channel_type"]
        defaults = {"length": int(config.get("length", 100)), "upper_dev": float(config.get("upper_dev", 2)), "lower_dev": float(config.get("lower_dev", 2)), "width_coeff": float(config.get("width_coeff", 1)), "window_type": "continuous", "interval_step": 1}
        channel = lrc(candles, defaults) if channel_type == "lrc" else regression_channel(candles, defaults) if channel_type == "regression" else trend_channel(candles, {"length": defaults["length"]})
        key = config.get("line", "middle"); key = {"middle": "middle_line", "upper": "top_line", "lower": "bottom_line"}.get(key, key) if channel_type == "trend" else key
        line = channel.get(key)
        if line is None or len(line) == 0: raise InsufficientReferenceData("channel respect has insufficient channel data")
        from .rule_engine import _line_touch
        touches = [index for index, value in enumerate(line) if _line_touch(candles[len(candles)-len(line)+index], float(value), float(config.get("tolerance_pct", 0)), config.get("touch_type", "wick"))]
        cluster_gap = max(1, int(config.get("cluster_gap", 3))); clusters = []
        for index in touches:
            if not clusters or index - clusters[-1] > cluster_gap: clusters.append(index)
        count = len(clusters); minimum = config.get("min_respect"); maximum = config.get("max_respect")
        passed = (minimum is None or count >= int(minimum)) and (maximum is None or count <= int(maximum))
        return {"filter": "channel_respect", "passed": passed, "values": {"touch_count": count, "indexes": clusters}}

    @staticmethod
    def _confluence(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        sources = config.get("sources") or []
        if len(sources) != 2: raise ValueError("confluence requires exactly two explicit sources")
        values = []
        for source in sources:
            channel_config = {"length": int(source.get("length", 100)), "upper_dev": float(source.get("upper_dev", 2)), "lower_dev": float(source.get("lower_dev", 2)), "width_coeff": float(source.get("width_coeff", 1)), "window_type": source.get("window_type", "continuous"), "interval_step": int(source.get("interval_step", 1))}
            from .custom_engine import lrc, regression_channel, trend_channel
            channel = lrc(candles, channel_config) if source["channel_type"] == "lrc" else regression_channel(candles, channel_config) if source["channel_type"] == "regression" else trend_channel(candles, channel_config)
            key = source.get("selection", "middle"); key = {"top_zone": "top_line", "bottom_zone": "bottom_line"}.get(key, key)
            series = channel.get(key)
            if series is None or len(series) == 0: raise InsufficientReferenceData("confluence source has insufficient data")
            values.append(float(series[-1]))
        price = float(candles[-1]["close"]); tolerance = abs(price) * float(config.get("tolerance_pct", 0.1)) / 100; kind = config.get("type")
        near = abs(values[0] - values[1]) <= tolerance
        passed = near and (price >= max(values) - tolerance if kind == "bullish" else price <= min(values) + tolerance if kind == "bearish" else price > max(values) + tolerance if kind == "breakout" else True if kind == "any" else False)
        return {"filter": "confluence", "passed": passed, "values": {"price": price, "sources": values, "near": near}}
