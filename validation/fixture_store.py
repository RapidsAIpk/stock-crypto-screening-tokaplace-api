from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from validation.spec import ValidationSpec
from validation.massive.client import MassiveResponse
from validation.twelve.client import TwelveResponse


INDICATORS = ("rsi", "aroon", "macd", "ema")


class FixtureIntegrityError(RuntimeError):
    pass


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _csv_bytes(values: list[dict[str, Any]]) -> bytes:
    fieldnames: list[str] = []
    for row in values:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(values)
    return stream.getvalue().encode("utf-8")


def _safe_symbol(symbol: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("._")
    if not normalized:
        raise ValueError("symbol cannot be converted to a safe fixture path")
    return normalized


class FixtureStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def run_path(self, spec: ValidationSpec) -> Path:
        return self.root / "twelve" / _safe_symbol(spec.symbol) / spec.run_id

    def massive_run_path(self, spec: ValidationSpec) -> Path:
        return self.root / "massive" / _safe_symbol(spec.symbol) / spec.run_id

    def results_path(self, spec: ValidationSpec) -> Path:
        return self.root / "results" / _safe_symbol(spec.symbol) / spec.run_id

    def assert_run_available(self, spec: ValidationSpec) -> None:
        if self.run_path(spec).exists():
            raise FileExistsError(
                f"validation run '{spec.run_id}' is already frozen and cannot be overwritten"
            )

    def assert_massive_run_available(self, spec: ValidationSpec) -> None:
        if self.massive_run_path(spec).exists():
            raise FileExistsError(
                f"Massive run '{spec.run_id}' is already frozen and cannot be overwritten"
            )

    def freeze_twelve_run(
        self,
        spec: ValidationSpec,
        candles: TwelveResponse,
        indicators: Mapping[str, TwelveResponse],
    ) -> Path:
        self.assert_run_available(spec)
        missing = [name for name in INDICATORS if name not in indicators]
        if missing:
            raise ValueError(f"missing indicator responses: {missing}")

        final_path = self.run_path(spec)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = Path(
            tempfile.mkdtemp(prefix=f".{spec.run_id}-", dir=final_path.parent)
        ).resolve()
        if staging_path.parent != final_path.parent.resolve():
            raise FixtureIntegrityError("staging directory escaped the fixture root")

        try:
            bundle_summaries: dict[str, Any] = {}
            for name in INDICATORS:
                bundle_summaries[name] = self._write_bundle(
                    staging_path / name,
                    candles,
                    indicators[name],
                )

            manifest = {
                "schema_version": 1,
                "run_id": spec.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "code_revision": os.getenv("GIT_COMMIT", "unknown"),
                "spec": spec.contract_dict(),
                "requests": {
                    "time_series": {
                        "endpoint": candles.endpoint,
                        "params": candles.request_params,
                        "fetched_at": candles.fetched_at,
                    },
                    **{
                        name: {
                            "endpoint": indicators[name].endpoint,
                            "params": indicators[name].request_params,
                            "fetched_at": indicators[name].fetched_at,
                        }
                        for name in INDICATORS
                    },
                },
                "provider_metadata": {
                    "time_series": candles.payload.get("meta", {}),
                    **{
                        name: indicators[name].payload.get("meta", {})
                        for name in INDICATORS
                    },
                },
                "provider_warnings": {
                    endpoint: response.payload.get("warning")
                    for endpoint, response in {
                        "time_series": candles,
                        **dict(indicators),
                    }.items()
                    if response.payload.get("warning")
                },
                "bundles": bundle_summaries,
            }
            manifest_bytes = _json_bytes(manifest)
            self._write_new(staging_path / "run_manifest.json", manifest_bytes)
            self._write_new(
                staging_path / "checksums.sha256",
                f"{_sha256(manifest_bytes)}  run_manifest.json\n".encode("ascii"),
            )
            os.replace(staging_path, final_path)
        except Exception:
            if staging_path.exists() and staging_path.parent == final_path.parent.resolve():
                shutil.rmtree(staging_path)
            raise
        return final_path

    def freeze_massive_run(
        self,
        spec: ValidationSpec,
        response: MassiveResponse,
        candles: list[dict[str, Any]],
    ) -> Path:
        self.assert_massive_run_available(spec)
        final_path = self.massive_run_path(spec)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = Path(
            tempfile.mkdtemp(prefix=f".{spec.run_id}-", dir=final_path.parent)
        ).resolve()
        if staging_path.parent != final_path.parent.resolve():
            raise FixtureIntegrityError("staging directory escaped the fixture root")

        try:
            csv_bytes = _csv_bytes(candles)
            raw_checksum = _sha256(response.body)
            csv_checksum = _sha256(csv_bytes)
            manifest = {
                "schema_version": 1,
                "run_id": spec.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "code_revision": os.getenv("GIT_COMMIT", "unknown"),
                "spec": spec.contract_dict(),
                "request": {
                    "endpoint": response.endpoint,
                    "params": response.request_params,
                    "fetched_at": response.fetched_at,
                },
                "provider_metadata": {
                    key: value
                    for key, value in response.payload.items()
                    if key != "results"
                },
                "raw_checksum": raw_checksum,
                "derived_files": {
                    "candles.csv": {
                        "sha256": csv_checksum,
                        "source_sha256": raw_checksum,
                    }
                },
            }
            manifest_bytes = _json_bytes(manifest)
            files = {
                "candles.raw.json": response.body,
                "candles.csv": csv_bytes,
                "run_manifest.json": manifest_bytes,
            }
            for filename, content in files.items():
                self._write_new(staging_path / filename, content)
            checksum_lines = [
                f"{_sha256(content)}  {filename}"
                for filename, content in sorted(files.items())
            ]
            self._write_new(
                staging_path / "checksums.sha256",
                ("\n".join(checksum_lines) + "\n").encode("ascii"),
            )
            os.replace(staging_path, final_path)
        except Exception:
            if staging_path.exists() and staging_path.parent == final_path.parent.resolve():
                shutil.rmtree(staging_path)
            raise
        return final_path

    def _write_bundle(
        self,
        bundle_path: Path,
        candles: TwelveResponse,
        indicator: TwelveResponse,
    ) -> dict[str, Any]:
        bundle_path.mkdir(parents=True, exist_ok=False)
        candle_csv = _csv_bytes(candles.payload["values"])
        indicator_csv = _csv_bytes(indicator.payload["values"])
        files = {
            "candles.raw.json": candles.body,
            "indicator.raw.json": indicator.body,
            "candles.csv": candle_csv,
            "reference.csv": indicator_csv,
        }
        for filename, content in files.items():
            self._write_new(bundle_path / filename, content)

        raw_checksums = {
            "candles.raw.json": _sha256(candles.body),
            "indicator.raw.json": _sha256(indicator.body),
        }
        bundle_manifest = {
            "indicator": indicator.endpoint,
            "raw_checksums": raw_checksums,
            "derived_files": {
                "candles.csv": {
                    "sha256": _sha256(candle_csv),
                    "source_sha256": raw_checksums["candles.raw.json"],
                },
                "reference.csv": {
                    "sha256": _sha256(indicator_csv),
                    "source_sha256": raw_checksums["indicator.raw.json"],
                },
            },
        }
        bundle_manifest_bytes = _json_bytes(bundle_manifest)
        self._write_new(bundle_path / "bundle_manifest.json", bundle_manifest_bytes)
        files["bundle_manifest.json"] = bundle_manifest_bytes

        checksum_lines = [
            f"{_sha256(content)}  {filename}"
            for filename, content in sorted(files.items())
        ]
        self._write_new(
            bundle_path / "checksums.sha256",
            ("\n".join(checksum_lines) + "\n").encode("ascii"),
        )
        return bundle_manifest

    @staticmethod
    def _write_new(path: Path, content: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(content)

    def verify_run(self, run_path: str | Path) -> None:
        resolved = Path(run_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise FixtureIntegrityError("run path is outside the fixture root") from exc
        if not resolved.is_dir():
            raise FixtureIntegrityError(f"fixture run does not exist: {resolved}")

        self._verify_checksum_file(resolved, resolved / "checksums.sha256")
        manifest = json.loads((resolved / "run_manifest.json").read_text("utf-8"))
        if manifest.get("run_id") != resolved.name:
            raise FixtureIntegrityError("run manifest ID does not match its directory")
        for indicator in INDICATORS:
            self._verify_checksum_file(
                resolved / indicator,
                resolved / indicator / "checksums.sha256",
            )

    def verify_massive_run(self, run_path: str | Path) -> None:
        resolved = Path(run_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise FixtureIntegrityError("Massive run path is outside the fixture root") from exc
        if not resolved.is_dir():
            raise FixtureIntegrityError(f"Massive fixture run does not exist: {resolved}")
        self._verify_checksum_file(resolved, resolved / "checksums.sha256")
        manifest = json.loads((resolved / "run_manifest.json").read_text("utf-8"))
        if manifest.get("run_id") != resolved.name:
            raise FixtureIntegrityError("Massive manifest ID does not match its directory")

    def write_result_once(
        self,
        spec: ValidationSpec,
        filename: str,
        payload: Any,
    ) -> Path:
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("result filename must be a plain .json filename")
        directory = self.results_path(spec)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        self._write_new(path, _json_bytes(payload))
        return path

    def write_result(
        self,
        spec: ValidationSpec,
        filename: str,
        payload: Any,
    ) -> Path:
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("result filename must be a plain .json filename")
        directory = self.results_path(spec)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        content = _json_bytes(payload)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=directory,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path.exists() and temporary_path.parent.resolve() == directory.resolve():
                temporary_path.unlink()
            raise
        return path

    @staticmethod
    def _verify_checksum_file(base_path: Path, checksum_path: Path) -> None:
        if not checksum_path.is_file():
            raise FixtureIntegrityError(f"missing checksum file: {checksum_path}")
        for line in checksum_path.read_text("ascii").splitlines():
            expected, separator, filename = line.partition("  ")
            if not separator or not expected or not filename:
                raise FixtureIntegrityError(f"invalid checksum line: {line}")
            target = (base_path / filename).resolve()
            try:
                target.relative_to(base_path.resolve())
            except ValueError as exc:
                raise FixtureIntegrityError("checksum path escapes its bundle") from exc
            if not target.is_file() or _sha256(target.read_bytes()) != expected:
                raise FixtureIntegrityError(f"checksum mismatch: {target}")
