# models/filters.py
import re
from types import SimpleNamespace

try:
    from pydantic import BaseModel, Field, model_validator, conlist, field_validator

    PYDANTIC_V2 = True

    def channel_type_list():
        return conlist(ChannelType, min_length=2)

except ImportError:
    from pydantic import BaseModel, Field, conlist, root_validator, validator

    PYDANTIC_V2 = False

    def field_validator(*fields, mode="after", **kwargs):
        pre = mode == "before"

        def decorator(func):
            target = func.__func__ if isinstance(func, classmethod) else func
            return validator(*fields, pre=pre, allow_reuse=True)(target)

        return decorator

    def model_validator(*, mode="after"):
        if mode != "after":
            raise NotImplementedError("Only after model validators are supported in pydantic v1 compatibility mode")

        def decorator(func):
            @root_validator(pre=False, allow_reuse=True)
            def wrapper(cls, values):
                proxy = SimpleNamespace(**values)
                result = func(proxy)
                if isinstance(result, dict):
                    return result
                if isinstance(result, SimpleNamespace):
                    return vars(result)
                return values

            return wrapper

        return decorator

    def channel_type_list():
        return conlist(ChannelType, min_items=2)

from typing import List, Optional, Literal, Dict, Any

from core.config import settings


# --------------------------------------------------
# ENUMS
# --------------------------------------------------

AssetType = Literal["stocks", "crypto"]

ComplianceStatus = Literal[
    "compliant",
    "non-compliant",
    "questionable"
]

ConfluenceType = Literal[
    "bullish",
    "bearish",
    "role_reversal",
    "breakout",
    "any"
]

TimeframeMode = Literal[
    "single",
    "gate_entry"
]

IndicatorTimeframe = Literal[
    "single",
    "primary",
    "secondary"
]

IndicatorName = Literal[
    "rsi",
    "stochrsi",
    "wavetrend",
    "aroon",
    "adx",
    "vlr",
    "ema",
    "sma",
    "macd",
    "volume",
    "relative_volume",
    "current_volume",
    "float",
    "shares_outstanding",
    "volatility",
    "lrc",
    "regression",
    "trend",
    "linreg_candles"
]
MAX_MANUAL_SYMBOLS = 2000


def _config_attr(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _valid_confluence_selections(channel_type):
    normalized = str(channel_type or "").strip().lower()
    if normalized == "trend":
        return {
            "top_line",
            "middle_line",
            "bottom_line",
            "top_zone",
            "bottom_zone",
        }

    return {
        "upper",
        "middle",
        "lower",
    }

ChannelType = Literal[
    "lrc",
    "regression",
    "trend"
]

ChannelLine = Literal[
    "upper",
    "middle",
    "lower",
    "both",
    "upper_middle",
    "lower_middle",
    "all",
]

ConfluenceSelection = Literal[
    "upper",
    "middle",
    "lower",
    "top_line",
    "middle_line",
    "bottom_line",
    "top_zone",
    "bottom_zone",
]


# --------------------------------------------------
# INDICATOR CONFIG
# --------------------------------------------------

class IndicatorConfig(BaseModel):

    name: IndicatorName

    timeframe: IndicatorTimeframe

    config: Dict[str, Any] = Field(
        default_factory=dict
    )


# --------------------------------------------------
# CHANNEL RESPECT
# --------------------------------------------------

class ChannelRespectFilter(BaseModel):

    channel_type: ChannelType

    min_respect: Optional[int] = None

    max_respect: Optional[int] = None

    line: ChannelLine = "middle"

    tolerance_pct: float = 0.0

    cluster_gap: int = 3

    touch_type: Literal["wick", "body", "both"] = "wick"


# --------------------------------------------------
# CONFLUENCE
# --------------------------------------------------

class ConfluenceSource(BaseModel):

    id: Optional[str] = None

    channel_type: ChannelType

    selection: Optional[ConfluenceSelection] = None

    length: Optional[int] = None

    width_coeff: Optional[float] = None

    upper_dev: Optional[float] = None

    lower_dev: Optional[float] = None

    window_type: Optional[Literal["continuous", "interval"]] = None

    interval_step: Optional[int] = None


class ConfluenceConfig(BaseModel):

    type: ConfluenceType

    channels: Optional[List[ChannelType]] = None

    sources: Optional[List[ConfluenceSource]] = None

    liquidity_sweep: bool = False

    lookback_candles: int = 4

    tolerance_pct: float = 0.1

    @model_validator(mode="after")
    def validate_confluence_config(self):
        sources = list(getattr(self, "sources", None) or [])
        channels = list(getattr(self, "channels", None) or [])

        if sources:
            if len(sources) != 2:
                raise ValueError("confluence.sources must contain exactly 2 items")
        elif channels:
            if len(channels) != 2:
                raise ValueError("confluence.channels must contain exactly 2 items")
        else:
            raise ValueError("confluence requires exactly 2 selected sources")

        lookback = int(getattr(self, "lookback_candles", 4) or 4)
        if lookback < 1 or lookback > 4:
            raise ValueError("confluence.lookback_candles must be between 1 and 4")

        tolerance = float(getattr(self, "tolerance_pct", 0.1) or 0.0)
        if tolerance < 0:
            raise ValueError("confluence.tolerance_pct cannot be negative")

        for source in sources:
            channel_type = _config_attr(source, "channel_type")
            selection = _config_attr(source, "selection")
            if not selection:
                continue

            valid_selections = _valid_confluence_selections(channel_type)
            if selection not in valid_selections:
                raise ValueError(
                    f"confluence selection '{selection}' is invalid for channel_type '{channel_type}'"
                )

        return self


class PriceRangeFilter(BaseModel):
    min_price: Optional[float] = None
    max_price: Optional[float] = None


# --------------------------------------------------
# DEAD ASSETS (Omit Dead Stock / Crypto)
# --------------------------------------------------

DeadTrendType = Literal[
    "strong_dead_trend",
    "slow_bleeding_trend",
    "failed_recovery",
    "flat_dead_asset",
]

ALL_DEAD_TREND_TYPES = [
    "strong_dead_trend",
    "slow_bleeding_trend",
    "failed_recovery",
    "flat_dead_asset",
]


class DeadAssetsFilter(BaseModel):

    enabled: bool = True

    dead_trend_types: List[DeadTrendType] = Field(
        default_factory=lambda: list(ALL_DEAD_TREND_TYPES)
    )

    lower_highs_required: int = 3

    lower_lows_required: int = 3

    trend_source: Literal[
        "ema_50",
        "ema_100",
        "ema_200",
        "linear_regression",
    ] = "ema_200"

    recovery_lookback: int = 200

    volume_option: Literal["low", "declining", "either"] = "either"

    volatility_option: Literal["low_atr", "very_low_atr", "either"] = "either"

    bounce_threshold_pct: float = 20.0

    failure_window: int = 20

    recovery_override: Literal[
        "disabled",
        "wick_above_swing_high",
        "close_above_swing_high",
        "two_closes_above_swing_high",
    ] = "close_above_swing_high"

    @model_validator(mode="after")
    def validate_dead_assets_filter(self):
        if self.enabled and not self.dead_trend_types:
            raise ValueError(
                "dead_assets.dead_trend_types must include at least one type when enabled"
            )
        if self.lower_highs_required < 1:
            raise ValueError("dead_assets.lower_highs_required must be at least 1")
        if self.lower_lows_required < 1:
            raise ValueError("dead_assets.lower_lows_required must be at least 1")
        if self.recovery_lookback < 2:
            raise ValueError("dead_assets.recovery_lookback must be at least 2")
        if not (0 < self.bounce_threshold_pct <= 1000):
            raise ValueError("dead_assets.bounce_threshold_pct must be a positive percentage")
        if self.failure_window < 1:
            raise ValueError("dead_assets.failure_window must be at least 1")
        return self


# --------------------------------------------------
# MAIN REQUEST
# --------------------------------------------------

class ScreeningRequest(BaseModel):

    # -----------------------------
    # ASSET
    # -----------------------------
    asset_type: AssetType
    symbols: Optional[List[str]] = None

    # -----------------------------
    # STOCKS
    # -----------------------------
    stock_sources: Optional[List[str]] = None

    compliance_status: Optional[
        ComplianceStatus
    ] = None

    compliance_standards: Optional[
        List[str]
    ] = None

    # -----------------------------
    # CRYPTO
    # -----------------------------
    exchanges: Optional[List[str]] = None

    excluded_categories: Optional[
        List[str]
    ] = None

    # -----------------------------
    # TIMEFRAME
    # -----------------------------
    timeframe_mode: TimeframeMode

    single_timeframe: Optional[str] = None

    gate_timeframe: Optional[str] = None

    entry_timeframe: Optional[str] = None

    gate_session_id: Optional[str] = None

    # -----------------------------
    # INDICATORS
    # -----------------------------
    indicators: List[IndicatorConfig] = Field(
        default_factory=list
    )

    # -----------------------------
    # CHANNEL RESPECT
    # -----------------------------
    channel_respect: Optional[
        ChannelRespectFilter
    ] = None

    # -----------------------------
    # CONFLUENCE
    # -----------------------------
    confluence: Optional[
        ConfluenceConfig
    ] = None
    price_range: Optional[PriceRangeFilter] = None

    # -----------------------------
    # DEAD ASSETS
    # -----------------------------
    dead_assets: Optional[DeadAssetsFilter] = None

    asset_categories: Optional[List[str]] = None

    sectors: Optional[List[str]] = None


    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    @model_validator(mode="after")
    def validate_asset_logic(self):

        if self.symbols:
            return self

        if self.asset_type == "stocks":

            if not self.stock_sources:
                raise ValueError(
                    "Stocks require stock_sources"
                )

            supported_sources = {"zoya"}
            requested_sources = {
                source.lower().strip()
                for source in self.stock_sources
            }

            unsupported_sources = requested_sources - supported_sources

            if unsupported_sources:
                raise ValueError(
                    f"Unsupported stock_sources: {sorted(unsupported_sources)}"
                )

            if self.compliance_standards:
                raise ValueError(
                    "compliance_standards are not supported by the current Zoya universe data"
                )

        if self.asset_type != "stocks":
            if self.asset_categories:
                raise ValueError("asset_categories are only supported for stocks")
            if self.sectors:
                raise ValueError("sectors are only supported for stocks")

        return self

    @field_validator("asset_categories", mode="before")
    @classmethod
    def normalize_asset_categories(cls, value):
        if not value:
            return None

        supported = {
            "nasdaq",
            "nyse",
            "amex",
            "etf",
            "sp500",
            "dow_jones",
            "russell_2000",
        }
        cleaned = []
        seen = set()
        for item in value:
            if item is None:
                continue
            token = str(item).strip().lower().replace(" ", "_").replace("-", "_")
            if not token or token in seen:
                continue
            if token not in supported:
                raise ValueError(f"Unsupported asset category: {item}")
            seen.add(token)
            cleaned.append(token)

        return cleaned or None

    @field_validator("sectors", mode="before")
    @classmethod
    def normalize_sectors(cls, value):
        if not value:
            return None

        cleaned = []
        seen = set()
        for item in value:
            if item is None:
                continue
            sector = str(item).strip()
            if not sector or sector in seen:
                continue
            seen.add(sector)
            cleaned.append(sector)

        return cleaned or None

    @field_validator("exchanges", mode="before")
    @classmethod
    def normalize_exchanges(cls, value):
        if not value:
            return None

        cleaned = []
        seen = set()
        for item in value:
            if item is None:
                continue
            exchange = str(item).strip().lower()
            if not exchange or exchange in seen:
                continue
            seen.add(exchange)
            cleaned.append(exchange)

        return cleaned or None

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value):
        if not value:
            return None

        cleaned = []
        seen = set()
        for item in value:
            if item is None:
                continue
            symbol = str(item).strip().upper()
            if not symbol:
                continue
            if symbol in seen:
                continue
            seen.add(symbol)
            cleaned.append(symbol)

        try:
            configured_max = int(getattr(settings, "MANUAL_SYMBOLS_MAX", MAX_MANUAL_SYMBOLS))
        except Exception:
            configured_max = MAX_MANUAL_SYMBOLS
        if configured_max <= 0:
            return cleaned or None

        max_manual_symbols = max(1, configured_max)

        if len(cleaned) > max_manual_symbols:
            raise ValueError(f"symbols supports up to {max_manual_symbols} items")

        return cleaned or None


    @model_validator(mode="after")
    def validate_timeframes(self):

        if self.timeframe_mode == "single":

            if not self.single_timeframe:
                raise ValueError(
                    "single_timeframe must be provided when timeframe_mode='single'"
                )

            single_seconds = _timeframe_to_seconds(self.single_timeframe)
            if single_seconds is None:
                raise ValueError(
                    "single_timeframe has invalid format. Use values like 1m, 15m, 4h, 1day, 2day, 1w, 1mo."
                )

        if self.timeframe_mode == "gate_entry":

            if not self.gate_timeframe or not self.entry_timeframe:
                raise ValueError(
                    "gate_timeframe and entry_timeframe required when timeframe_mode='gate_entry'"
                )

            gate_seconds = _timeframe_to_seconds(self.gate_timeframe)
            entry_seconds = _timeframe_to_seconds(self.entry_timeframe)
            if gate_seconds is None:
                raise ValueError(
                    "gate_timeframe has invalid format. Use values like 1m, 15m, 4h, 1day, 2day, 1w, 1mo."
                )
            if entry_seconds is None:
                raise ValueError(
                    "entry_timeframe has invalid format. Use values like 1m, 15m, 4h, 1day, 2day, 1w, 1mo."
                )

            if gate_seconds <= entry_seconds:
                raise ValueError(
                    "gate_timeframe must be greater than entry_timeframe for gate_entry mode"
                )

        if self.price_range:
            min_price = self.price_range.min_price
            max_price = self.price_range.max_price
            if (
                min_price is not None
                and max_price is not None
                and float(min_price) > float(max_price)
            ):
                raise ValueError("price_range.min_price cannot be greater than price_range.max_price")

        return self


def _parse_timeframe(value: str) -> Optional[tuple[int, str]]:
    if not value:
        return None

    fixed = {
        "1m": (1, "m"),
        "5m": (5, "m"),
        "15m": (15, "m"),
        "30m": (30, "m"),
        "1h": (1, "h"),
        "4h": (4, "h"),
        "1day": (1, "d"),
    }

    lowered = str(value).strip().lower()
    if lowered in fixed:
        return fixed[lowered]

    match = re.match(
        r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days|w|wk|week|weeks|mo|mon|month|months)$",
        lowered,
    )
    if not match:
        return None

    amount = int(match.group(1))
    if amount <= 0:
        return None

    unit = match.group(2)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return amount, "m"
    if unit in {"h", "hr", "hour", "hours"}:
        return amount, "h"
    if unit in {"d", "day", "days"}:
        return amount, "d"
    if unit in {"w", "wk", "week", "weeks"}:
        return amount, "w"
    return amount, "mo"


def _timeframe_to_seconds(value: str) -> Optional[int]:
    parsed = _parse_timeframe(value)
    if not parsed:
        return None

    amount, unit = parsed
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 60 * 60
    if unit == "d":
        return amount * 24 * 60 * 60
    if unit == "w":
        return amount * 7 * 24 * 60 * 60
    return amount * 30 * 24 * 60 * 60
