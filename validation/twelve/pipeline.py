from __future__ import annotations

from pathlib import Path

from validation.fixture_store import FixtureStore
from validation.spec import ValidationSpec
from validation.twelve import aroon, candles, ema, macd, rsi
from validation.twelve.client import TwelveDataClient


class TwelveReferencePipeline:
    def __init__(self, client: TwelveDataClient, store: FixtureStore) -> None:
        self.client = client
        self.store = store

    def freeze(self, spec: ValidationSpec) -> Path:
        # Check before spending API credits on a run that is already frozen.
        self.store.assert_run_available(spec)
        candle_response = candles.fetch(self.client, spec)
        indicator_responses = {
            "rsi": rsi.fetch(self.client, spec),
            "aroon": aroon.fetch(self.client, spec),
            "macd": macd.fetch(self.client, spec),
            "ema": ema.fetch(self.client, spec),
        }
        return self.store.freeze_twelve_run(
            spec,
            candle_response,
            indicator_responses,
        )
