from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_BASE_URL = "https://api.massive.com"


class MassiveDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class MassiveResponse:
    endpoint: str
    request_params: dict[str, Any]
    body: bytes
    payload: dict[str, Any]
    fetched_at: str


class MassiveDataClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30,
        request_get: Callable[..., Any] | None = None,
    ) -> None:
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("MASSIVE_API_KEY or POLYGON_API_KEY is required")
        self._api_key = normalized_key
        self._base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session: requests.Session | None = None

        if request_get is not None:
            self._request_get = request_get
        else:
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                status=2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                backoff_factor=0.5,
                respect_retry_after_header=True,
            )
            self._session = requests.Session()
            self._session.mount("https://", HTTPAdapter(max_retries=retry))
            self._request_get = self._session.get

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    def get(self, endpoint: str, params: dict[str, Any]) -> MassiveResponse:
        public_params = dict(params)
        request_params = {**public_params, "apiKey": self._api_key}
        try:
            response = self._request_get(
                f"{self._base_url}/{endpoint.lstrip('/')}",
                params=request_params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MassiveDataError(f"Massive request failed for '{endpoint}': {exc}") from exc

        body = bytes(response.content)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MassiveDataError(f"Massive returned invalid JSON for '{endpoint}'") from exc
        if not isinstance(payload, dict):
            raise MassiveDataError(f"Massive returned a non-object for '{endpoint}'")
        status = str(payload.get("status") or "").upper()
        if status not in {"OK", "DELAYED"}:
            detail = payload.get("error") or payload.get("message") or "unknown API error"
            raise MassiveDataError(
                f"Massive API error for '{endpoint}': status={status or 'unknown'} detail={detail}"
            )

        return MassiveResponse(
            endpoint=endpoint,
            request_params=public_params,
            body=body,
            payload=payload,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
