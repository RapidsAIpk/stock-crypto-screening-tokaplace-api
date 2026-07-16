from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import SCHEMA_VERSION, ScreenerCase, canonical_json, semantic_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slice_candles_to_date(candles: list[dict[str, Any]], evaluation_date: str | None) -> list[dict[str, Any]]:
    if not evaluation_date:
        return candles
    normalized = str(evaluation_date).strip()
    sliced = [row for row in candles if str(row.get("date") or "") <= normalized]
    if not sliced:
        raise ValueError(f"evaluation_date '{evaluation_date}' is before the first candle")
    return sliced


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class FixtureStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def fixture_path(self, fixture_id: str) -> Path:
        return self.root / "fixtures" / fixture_id

    def create(
        self,
        fixture_id: str,
        candles_by_timeframe: dict[str, dict[str, list[dict[str, Any]]]],
        metadata: dict[str, dict[str, Any]],
        *,
        source: str = "massive",
        provider_requests: int = 0,
        provider_raw: dict[str, Any] | None = None,
    ) -> Path:
        target = self.fixture_path(fixture_id)
        if target.exists():
            raise FileExistsError(f"fixture '{fixture_id}' is immutable and already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{fixture_id}.", dir=target.parent))
        try:
            files: list[Path] = []
            symbols: set[str] = set()
            timeframes: set[str] = set()
            for timeframe, symbol_rows in sorted(candles_by_timeframe.items()):
                timeframes.add(timeframe)
                for symbol, rows in sorted(symbol_rows.items()):
                    normalized_symbol = symbol.upper()
                    symbols.add(normalized_symbol)
                    if not rows:
                        raise ValueError(f"fixture candles are empty for {normalized_symbol} {timeframe}")
                    for row in rows:
                        if any(row.get(flag) is False for flag in ("closed", "complete", "is_closed", "is_complete")):
                            raise ValueError(f"fixture contains an incomplete candle for {normalized_symbol} {timeframe}")
                        missing_fields = [field for field in ("open", "high", "low", "close", "volume") if field not in row]
                        if missing_fields:
                            raise ValueError(f"fixture candle for {normalized_symbol} is missing {missing_fields}")
                    path = temporary / "candles" / timeframe / f"{normalized_symbol}.json"
                    _atomic_json(path, rows)
                    files.append(path)
            metadata_path = temporary / "metadata.json"
            _atomic_json(metadata_path, {key.upper(): value for key, value in metadata.items()})
            files.append(metadata_path)
            if provider_raw is not None:
                raw_path = temporary / "provider_raw.audit.json"
                _atomic_json(raw_path, provider_raw)
                files.append(raw_path)
            checksums = {str(path.relative_to(temporary)).replace("\\", "/"): _sha256(path) for path in files}
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "fixture_id": fixture_id,
                "source": source,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "symbols": sorted(symbols),
                "timeframes": sorted(timeframes),
                "provider_requests": int(provider_requests),
                "checksums": checksums,
            }
            manifest["semantic_hash"] = semantic_hash({key: value for key, value in manifest.items() if key != "created_at"})
            _atomic_json(temporary / "manifest.json", manifest)
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return target

    def verify(self, fixture_id: str) -> dict[str, Any]:
        path = self.fixture_path(fixture_id)
        manifest = json.loads((path / "manifest.json").read_text("utf-8"))
        if manifest.get("fixture_id") != fixture_id:
            raise ValueError("fixture manifest ID mismatch")
        for relative, expected in manifest.get("checksums", {}).items():
            file_path = path / relative
            if not file_path.is_file() or _sha256(file_path) != expected:
                raise ValueError(f"fixture checksum mismatch: {relative}")
        return manifest

    def load_metadata(self, fixture_id: str) -> dict[str, dict[str, Any]]:
        self.verify(fixture_id)
        return json.loads((self.fixture_path(fixture_id) / "metadata.json").read_text("utf-8"))

    def load_candles(self, fixture_id: str, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        self.verify(fixture_id)
        path = self.fixture_path(fixture_id) / "candles" / timeframe / f"{symbol.upper()}.json"
        if not path.is_file():
            raise KeyError(f"fixture has no {timeframe} candles for {symbol.upper()}")
        rows = json.loads(path.read_text("utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"fixture candles are empty for {symbol.upper()}")
        dates = [str(row.get("datetime") or row.get("date") or row.get("time")) for row in rows]
        if len(dates) != len(set(dates)) or dates != sorted(dates):
            raise ValueError(f"fixture candles must be unique and ordered for {symbol.upper()}")
        return rows


class GoldenStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _candidate_path(self, candidate_id: str) -> Path:
        return self.root / "golden" / "candidates" / f"{candidate_id}.json"

    def _approved_path(self, golden_id: str) -> Path:
        return self.root / "golden" / "approved" / f"{golden_id}.json"

    def list_candidates(self) -> list[dict[str, Any]]:
        directory = self.root / "golden" / "candidates"
        if not directory.is_dir():
            return []
        candidates = []
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text("utf-8"))
            candidates.append({
                "candidate_id": payload.get("candidate_id") or path.stem,
                "case_id": payload.get("case_id"),
                "status": payload.get("reference", {}).get("status"),
                "expected_symbols": payload.get("reference", {}).get("expected_symbols", []),
                "path": str(path),
            })
        return candidates

    def resolve_candidate_id(self, candidate_or_case_id: str) -> str:
        candidate_or_case_id = str(candidate_or_case_id).strip()
        if not candidate_or_case_id:
            raise ValueError("candidate is required")
        if self._candidate_path(candidate_or_case_id).is_file():
            return candidate_or_case_id
        matches = [
            candidate
            for candidate in self.list_candidates()
            if candidate.get("case_id") == candidate_or_case_id
        ]
        if len(matches) == 1:
            return str(matches[0]["candidate_id"])
        if len(matches) > 1:
            raise ValueError(f"multiple candidates match case_id '{candidate_or_case_id}'")
        raise FileNotFoundError(f"candidate '{candidate_or_case_id}' does not exist")

    def write_candidate(self, case: ScreenerCase, fixture_manifest: dict[str, Any], reference: dict[str, Any]) -> tuple[str, Path]:
        semantic = {
            "schema_version": SCHEMA_VERSION,
            "case_id": case.case_id,
            "case_checksum": case.checksum,
            "fixture_id": case.fixture_id,
            "fixture_hash": fixture_manifest["semantic_hash"],
            "reference": reference,
        }
        candidate_id = semantic_hash(semantic)[:24]
        path = self._candidate_path(candidate_id)
        payload = {**semantic, "candidate_id": candidate_id, "generated_at": datetime.now(timezone.utc).isoformat()}
        if path.exists():
            existing = json.loads(path.read_text("utf-8"))
            if {key: existing.get(key) for key in semantic} != semantic:
                raise ValueError("candidate ID collision")
        else:
            _atomic_json(path, payload)
        review_path = path.with_suffix(".md")
        lines = [
            f"# Reference Candidate: {case.case_id}",
            "",
            f"Candidate ID: `{candidate_id}`",
            f"Fixture: `{case.fixture_id}`",
            f"Status: `{reference.get('status')}`",
            f"Expected symbols: {', '.join(reference.get('expected_symbols', [])) or 'none'}",
            f"Excluded symbols: {', '.join(reference.get('excluded_symbols', [])) or 'none'}",
            f"Insufficient data: {', '.join(reference.get('insufficient_data_symbols', [])) or 'none'}",
            "",
            "## Symbol Evidence",
            "",
        ]
        for symbol, evidence in sorted(reference.get("symbol_evidence", {}).items()):
            lines.extend([f"### {symbol}", "", f"Expected: `{evidence.get('expected')}`", f"Status: `{evidence.get('status')}`", ""])
            for rule in evidence.get("rules", []):
                label = rule.get("indicator") or rule.get("filter") or "rule"
                lines.append(f"- `{label}` passed=`{rule.get('passed')}` values=`{canonical_json(rule.get('values', {}))}`")
            if evidence.get("error"):
                lines.append(f"- Error: `{evidence['error']}`")
            lines.append("")
        review_path.write_text("\n".join(lines), "utf-8")
        return candidate_id, path

    def approve(self, candidate_id: str, approver: str) -> tuple[str, Path]:
        candidate_id = self.resolve_candidate_id(candidate_id)
        candidate_path = self._candidate_path(candidate_id)
        candidate = json.loads(candidate_path.read_text("utf-8"))
        approver = str(approver).strip()
        if not approver:
            raise ValueError("approver is required")
        if candidate.get("reference", {}).get("status") != "evaluated":
            raise ValueError("only fully evaluated reference candidates can be approved")
        golden_id = f"{candidate['case_id']}-{candidate_id}"
        path = self._approved_path(golden_id)
        if path.exists():
            raise FileExistsError(f"golden reference '{golden_id}' is immutable")
        _atomic_json(path, {**candidate, "golden_id": golden_id, "approved_by": approver, "approved_at": datetime.now(timezone.utc).isoformat()})
        return golden_id, path

    def load_approved(self, golden_id: str) -> dict[str, Any]:
        path = self._approved_path(golden_id)
        if not path.is_file():
            raise FileNotFoundError(f"approved golden reference '{golden_id}' does not exist")
        return json.loads(path.read_text("utf-8"))

    def find_approved(self, case: ScreenerCase) -> dict[str, Any] | None:
        directory = self.root / "golden" / "approved"
        if not directory.is_dir():
            return None
        matches = []
        for path in directory.glob("*.json"):
            payload = json.loads(path.read_text("utf-8"))
            if payload.get("case_id") == case.case_id and payload.get("case_checksum") == case.checksum:
                matches.append((path, payload))
        if len(matches) > 1:
            raise ValueError(f"multiple approved golden references match case '{case.case_id}'")
        return matches[0][1] if matches else None

    def verify(self, golden: dict[str, Any], case: ScreenerCase, fixture_manifest: dict[str, Any], current_reference: dict[str, Any]) -> str | None:
        if golden.get("case_checksum") != case.checksum:
            return "case checksum changed"
        if golden.get("fixture_hash") != fixture_manifest.get("semantic_hash"):
            return "fixture checksum changed"
        if canonical_json(golden.get("reference")) != canonical_json(current_reference):
            return "independent reference output changed"
        return None
