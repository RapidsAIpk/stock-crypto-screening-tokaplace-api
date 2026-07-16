from __future__ import annotations

from pathlib import Path
from typing import Any

from validation.alignment import CandleAlignmentAuditor
from validation.fixture_store import FixtureStore
from validation.massive.fetcher import MassiveCandleFetcher
from validation.spec import ValidationSpec


class MassiveValidationPipeline:
    def __init__(
        self,
        fetcher: MassiveCandleFetcher,
        store: FixtureStore,
        auditor: CandleAlignmentAuditor | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.store = store
        self.auditor = auditor or CandleAlignmentAuditor(store)

    def freeze_and_audit(
        self,
        spec: ValidationSpec,
        twelve_run_path: str | Path | None = None,
    ) -> dict[str, Any]:
        twelve_path = Path(twelve_run_path or self.store.run_path(spec))
        self.store.verify_run(twelve_path)
        self.store.assert_massive_run_available(spec)
        response, candles = self.fetcher.fetch(spec)
        massive_path = self.store.freeze_massive_run(spec, response, candles)
        alignment = self.auditor.audit(spec, twelve_path, massive_path)
        report_path = self.store.write_result_once(
            spec,
            "candle_alignment.json",
            alignment,
        )
        return {
            "massive_run_path": massive_path,
            "alignment_report_path": report_path,
            "alignment": alignment,
        }
