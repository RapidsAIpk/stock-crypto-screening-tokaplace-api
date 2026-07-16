from __future__ import annotations

import sys
from typing import Any

import pandas as pd
import requests


# ============================================================
# PUT YOUR TWELVE DATA API KEY HERE
# ============================================================
API_KEY = "none"


# ============================================================
# SETTINGS
# ============================================================
SYMBOL = "BTC/USD"
INTERVAL = "1h"
OUTPUT_SIZE = 500

EMA_PERIOD = 20
RSI_PERIOD = 14
ATR_PERIOD = 14

OUTPUT_FILE = "BTC_USD_1h_with_indicators.csv"

BASE_URL = "https://api.twelvedata.com"


def make_request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """
    Send a request to Twelve Data and return the JSON response.
    Raises a readable error when the API rejects the request.
    """
    request_params = {
        **params,
        "apikey": API_KEY,
    }

    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(
            url,
            params=request_params,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"HTTP request failed for endpoint '{endpoint}': {exc}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Twelve Data returned invalid JSON for '{endpoint}'."
        ) from exc

    if data.get("status") == "error":
        error_message = data.get("message", "Unknown Twelve Data API error")
        error_code = data.get("code", "unknown")

        raise RuntimeError(
            f"Twelve Data API error on '{endpoint}': "
            f"{error_message} (code: {error_code})"
        )

    return data


def fetch_time_series() -> pd.DataFrame:
    """
    Fetch OHLCV candles.
    """
    print("Fetching OHLCV data...")

    data = make_request(
        endpoint="time_series",
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "outputsize": OUTPUT_SIZE,
            "order": "ASC",
            "timezone": "UTC",
        },
    )

    values = data.get("values")

    if not values:
        raise RuntimeError("No OHLCV values were returned.")

    df = pd.DataFrame(values)

    required_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
    ]

    missing_columns = [
        column for column in required_columns if column not in df.columns
    ]

    if missing_columns:
        raise RuntimeError(
            f"OHLCV response is missing columns: {missing_columns}"
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True,
        errors="coerce",
    )

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    return df


def fetch_indicator(
    endpoint: str,
    params: dict[str, Any],
    rename_columns: dict[str, str],
) -> pd.DataFrame:
    """
    Fetch one technical indicator and rename its output columns.
    """
    print(f"Fetching {endpoint.upper()}...")

    data = make_request(
        endpoint=endpoint,
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "outputsize": OUTPUT_SIZE,
            "order": "ASC",
            "timezone": "UTC",
            **params,
        },
    )

    values = data.get("values")

    if not values:
        raise RuntimeError(
            f"No values were returned for indicator '{endpoint}'."
        )

    df = pd.DataFrame(values)

    if "datetime" not in df.columns:
        raise RuntimeError(
            f"Indicator '{endpoint}' response has no datetime column."
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True,
        errors="coerce",
    )

    df = df.rename(columns=rename_columns)

    indicator_columns = [
        column
        for column in rename_columns.values()
        if column in df.columns
    ]

    for column in indicator_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    return df[["datetime", *indicator_columns]]


def main() -> None:
    if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
        print("Error: Put your Twelve Data API key in API_KEY.")
        sys.exit(1)

    try:
        # 1. Fetch OHLCV
        result = fetch_time_series()

        # 2. Fetch RSI
        rsi_df = fetch_indicator(
            endpoint="rsi",
            params={
                "time_period": RSI_PERIOD,
                "series_type": "close",
            },
            rename_columns={
                "rsi": f"rsi_{RSI_PERIOD}",
            },
        )

        # 3. Fetch EMA
        ema_df = fetch_indicator(
            endpoint="ema",
            params={
                "time_period": EMA_PERIOD,
                "series_type": "close",
            },
            rename_columns={
                "ema": f"ema_{EMA_PERIOD}",
            },
        )

        # 4. Fetch MACD
        macd_df = fetch_indicator(
            endpoint="macd",
            params={
                "fast_period": 12,
                "slow_period": 26,
                "signal_period": 9,
                "series_type": "close",
            },
            rename_columns={
                "macd": "macd",
                "macd_signal": "macd_signal",
                "macd_hist": "macd_histogram",
            },
        )

        # 5. Fetch ATR
        atr_df = fetch_indicator(
            endpoint="atr",
            params={
                "time_period": ATR_PERIOD,
            },
            rename_columns={
                "atr": f"atr_{ATR_PERIOD}",
            },
        )

        # 6. Fetch Bollinger Bands
        bbands_df = fetch_indicator(
            endpoint="bbands",
            params={
                "time_period": 20,
                "sd": 2,
                "series_type": "close",
            },
            rename_columns={
                "upper_band": "bb_upper",
                "middle_band": "bb_middle",
                "lower_band": "bb_lower",
            },
        )

        # Merge all indicator tables with OHLCV by datetime
        indicator_frames = [
            rsi_df,
            ema_df,
            macd_df,
            atr_df,
            bbands_df,
        ]

        for indicator_df in indicator_frames:
            result = result.merge(
                indicator_df,
                on="datetime",
                how="left",
            )

        # Sort from oldest to newest
        result = result.sort_values("datetime")

        # Remove duplicate timestamps if any
        result = result.drop_duplicates(
            subset=["datetime"],
            keep="last",
        )

        # Put columns in a clean order
        preferred_columns = [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            f"rsi_{RSI_PERIOD}",
            f"ema_{EMA_PERIOD}",
            "macd",
            "macd_signal",
            "macd_histogram",
            f"atr_{ATR_PERIOD}",
            "bb_upper",
            "bb_middle",
            "bb_lower",
        ]

        available_columns = [
            column
            for column in preferred_columns
            if column in result.columns
        ]

        result = result[available_columns]

        result.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        print()
        print("Success!")
        print(f"Rows saved: {len(result)}")
        print(f"Output file: {OUTPUT_FILE}")
        print()
        print(result.tail(10).to_string(index=False))

    except RuntimeError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()