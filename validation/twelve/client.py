from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://api.twelvedata.com"


class TwelveDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class TwelveResponse:
    endpoint: str
    request_params: dict[str, Any]
    body: bytes
    payload: dict[str, Any]
    fetched_at: str


class TwelveDataClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30,
        request_get: Callable[..., Any] | None = None,
    ) -> None:
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        self._api_key = normalized_key
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

    @staticmethod
    def _redact_request_error(exc: requests.RequestException) -> str:
        message = str(exc)
        request = getattr(exc, "request", None)
        if request is None or not getattr(request, "url", None):
            return message
        parsed = urlsplit(request.url)
        redacted_query = urlencode(
            [
                (key, "***" if key.lower() == "apikey" else value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        redacted_url = urlunsplit(parsed._replace(query=redacted_query))
        return message.replace(request.url, redacted_url)

    def get(self, endpoint: str, params: dict[str, Any]) -> TwelveResponse:
        public_params = dict(params)
        request_params = {**public_params, "apikey": self._api_key}
        try:
            response = self._request_get(
                f"{BASE_URL}/{endpoint}",
                params=request_params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = self._redact_request_error(exc)
            raise TwelveDataError(
                f"Twelve Data request failed for '{endpoint}': {detail}"
            ) from exc

        body = bytes(response.content)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TwelveDataError(
                f"Twelve Data returned invalid JSON for '{endpoint}'"
            ) from exc
        if not isinstance(payload, dict):
            raise TwelveDataError(f"Twelve Data returned a non-object for '{endpoint}'")
        if payload.get("status") == "error" or payload.get("code"):
            message = payload.get("message") or "unknown API error"
            code = payload.get("code", "unknown")
            raise TwelveDataError(
                f"Twelve Data API error for '{endpoint}': {message} (code: {code})"
            )

        return TwelveResponse(
            endpoint=endpoint,
            request_params=public_params,
            body=body,
            payload=payload,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
