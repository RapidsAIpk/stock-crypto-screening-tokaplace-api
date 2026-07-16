# models/results.py

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ResultsBaseModel(BaseModel):
    def model_dump(self, *args, **kwargs):
        if hasattr(super(), "model_dump"):
            return super().model_dump(*args, **kwargs)
        return self.dict(*args, **kwargs)

    def model_dump_json(self, *args, **kwargs):
        if hasattr(super(), "model_dump_json"):
            return super().model_dump_json(*args, **kwargs)
        return self.json(*args, **kwargs)


class ScreeningResult(ResultsBaseModel):

    symbol: str

    price: float

    asset_type: str

    data_source: str

    timeframe: str
    scan_stage: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    sector: Optional[str] = None
    asset_categories: Optional[List[str]] = None
    cmc_id: Optional[int] = None
    rank: Optional[int] = None
    compliance_status: Optional[str] = None
    report_date: Optional[str] = None
    purification_ratio: Optional[float] = None
    candles_count: Optional[int] = None
    last_candle_time: Optional[int] = None

    exchange: Optional[str] = None
    exchange_availability: Optional[List[str]] = None

    note: Optional[str] = None

    stickers: List[str] = Field(
        default_factory=list
    )
    matched_indicators: Optional[List[str]] = None


class ScreeningResponse(ResultsBaseModel):

    results: List[ScreeningResult] = Field(
        default_factory=list
    )

    gate_session_id: Optional[str] = None


class CryptoExchangeOption(ResultsBaseModel):
    exchange: str
    coin_count: int


class CryptoExchangeOptionsResponse(ResultsBaseModel):
    exchanges: List[CryptoExchangeOption] = Field(default_factory=list)


class StockFilterOption(ResultsBaseModel):
    id: str
    label: str


class StockFilterOptionsResponse(ResultsBaseModel):
    asset_categories: List[StockFilterOption] = Field(default_factory=list)
    sectors: List[str] = Field(default_factory=list)


class IndicatorDetail(ResultsBaseModel):
    name: str
    timeframe_scope: Optional[str] = None
    passed: bool
    sticker: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class FilterDetail(ResultsBaseModel):
    name: str
    passed: bool
    summary: Optional[str] = None
    sticker: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class MarketDataDetail(ResultsBaseModel):
    candles_provider: Optional[str] = None
    next_refresh_at: Optional[int] = None
    shares_outstanding: Optional[float] = None
    float_shares: Optional[float] = None
    last_candle: Optional[Dict[str, Any]] = None
    recent_candles: List[Dict[str, Any]] = Field(default_factory=list)


class ScreeningResultDetail(ScreeningResult):
    asset_metadata: Dict[str, Any] = Field(default_factory=dict)
    request_filters: Dict[str, Any] = Field(default_factory=dict)
    indicator_details: List[IndicatorDetail] = Field(default_factory=list)
    filter_details: List[FilterDetail] = Field(default_factory=list)
    market_data: MarketDataDetail = Field(default_factory=MarketDataDetail)
    channels: Dict[str, Any] = Field(default_factory=dict)
    confluence_channels: Dict[str, Any] = Field(default_factory=dict)


class ScreeningDetailResponse(ResultsBaseModel):
    detail: Optional[ScreeningResultDetail] = None
