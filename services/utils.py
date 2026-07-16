# services/utils.py


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _candle_body(candle):
    return abs(_safe_float(candle["close"]) - _safe_float(candle["open"]))


def _candle_range(candle):
    return max(_safe_float(candle["high"]) - _safe_float(candle["low"]), 1e-9)


def _upper_wick(candle):
    return _safe_float(candle["high"]) - max(_safe_float(candle["open"]), _safe_float(candle["close"]))


def _lower_wick(candle):
    return min(_safe_float(candle["open"]), _safe_float(candle["close"])) - _safe_float(candle["low"])


def _is_bullish(candle):
    return _safe_float(candle["close"]) > _safe_float(candle["open"])


def _is_bearish(candle):
    return _safe_float(candle["close"]) < _safe_float(candle["open"])


def _preceding_trend(candles, index, lookback=3):
    if index - lookback < 0:
        return None

    closes = [_safe_float(candles[i]["close"]) for i in range(index - lookback, index)]
    if len(closes) < 2:
        return None

    if all(closes[i] < closes[i + 1] for i in range(len(closes) - 1)):
        return "up"
    if all(closes[i] > closes[i + 1] for i in range(len(closes) - 1)):
        return "down"

    return None


BULLISH_PATTERNS = {
    "bullish_engulfing",
    "hammer",
    "inverted_hammer",
    "morning_star",
    "piercing_line",
    "three_white_soldiers",
    "bullish_marubozu",
    "strong_breakout_candle",
    "tweezer_bottom",
    "bullish_pin_bar",
    "double_bottom",
}

BEARISH_PATTERNS = {
    "bearish_engulfing",
    "shooting_star",
    "evening_star",
    "dark_cloud_cover",
    "three_black_crows",
    "bearish_marubozu",
    "strong_breakdown_candle",
    "tweezer_top",
    "bearish_pin_bar",
    "double_top",
}

STRONG_BULLISH_PATTERNS = {
    "three_white_soldiers",
    "bullish_marubozu",
    "strong_breakout_candle",
}

STRONG_BEARISH_PATTERNS = {
    "three_black_crows",
    "bearish_marubozu",
    "strong_breakdown_candle",
}


def humanize_token(value):
    return str(value or "").replace("_", " ").strip().title()


def format_decimal(value, decimals=2, signed=False):
    number = _safe_float(value)
    template = f"{{:{'+' if signed else ''}.{int(decimals)}f}}"
    return template.format(number)


def format_compact_number(value, decimals=2):
    number = abs(_safe_float(value))
    sign = "-" if _safe_float(value) < 0 else ""

    if number >= 1_000_000_000_000:
        return f"{sign}{number / 1_000_000_000_000:.{int(decimals)}f}T"
    if number >= 1_000_000_000:
        return f"{sign}{number / 1_000_000_000:.{int(decimals)}f}B"
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.{int(decimals)}f}M"
    if number >= 1_000:
        return f"{sign}{number / 1_000:.{int(decimals)}f}K"
    if number.is_integer():
        return f"{sign}{int(number)}"
    return f"{sign}{number:.{int(decimals)}f}"


def format_price_value(value):
    number = _safe_float(value)
    abs_number = abs(number)

    if abs_number >= 1:
        return f"${number:,.2f}"
    if abs_number >= 0.01:
        return f"${number:,.4f}"
    return f"${number:,.6f}"


def format_window_label(window):
    count = max(1, int(window or 1))
    suffix = "Candle" if count == 1 else "Candles"
    return f"Last {count} {suffix}"


def build_pattern_label(config):
    confirmation_types = list(config.get("confirmation_types") or [])
    confirmation_type = config.get("confirmation_type")
    confirmation_patterns = list(config.get("confirmation_patterns") or [])

    if confirmation_type and confirmation_type not in confirmation_types:
        confirmation_types = [confirmation_type, *confirmation_types]

    if not config.get("confirmation"):
        return "No Pattern"

    if confirmation_patterns:
        return humanize_token(confirmation_patterns[0])

    if confirmation_types:
        return humanize_token(confirmation_types[0])

    return "No Pattern"


def build_indicator_sticker(name, condition, config, length=None, window=None, decision=None):
    title = str(name)
    if length is not None:
        title = f"{title} ({int(length)})"

    if window is None:
        window = config.get("window", 1) or 1

    parts = [title]
    if decision:
        parts.append(str(decision))
    parts.extend(
        [
            condition,
            build_pattern_label(config),
            format_window_label(window),
        ]
    )
    return " | ".join(str(part) for part in parts if part)


def detect_candlestick_patterns(candles, index):
    if index < 0 or index >= len(candles):
        return set()

    current = candles[index]
    previous = candles[index - 1] if index - 1 >= 0 else None
    prior = candles[index - 2] if index - 2 >= 0 else None
    patterns = set()
    tolerance = _safe_float(current["close"], 1.0) * 0.001

    body = _candle_body(current)
    candle_range = _candle_range(current)
    upper_wick = _upper_wick(current)
    lower_wick = _lower_wick(current)

    if previous:
        prev_open = _safe_float(previous["open"])
        prev_close = _safe_float(previous["close"])
        cur_open = _safe_float(current["open"])
        cur_close = _safe_float(current["close"])

        if _is_bearish(previous) and _is_bullish(current):
            if cur_open <= prev_close and cur_close >= prev_open:
                patterns.add("bullish_engulfing")
            prev_mid = (prev_open + prev_close) / 2.0
            prev_low = _safe_float(previous["low"])
            if cur_open < prev_low and cur_close > prev_mid and cur_close < prev_open:
                patterns.add("piercing_line")

        if _is_bullish(previous) and _is_bearish(current):
            if cur_open >= prev_close and cur_close <= prev_open:
                patterns.add("bearish_engulfing")
            prev_mid = (prev_open + prev_close) / 2.0
            prev_high = _safe_float(previous["high"])
            if cur_open > prev_high and cur_close < prev_mid and cur_close > prev_open:
                patterns.add("dark_cloud_cover")

        if abs(_safe_float(current["low"]) - _safe_float(previous["low"])) <= tolerance and _is_bullish(current):
            patterns.add("tweezer_bottom")
        if abs(_safe_float(current["high"]) - _safe_float(previous["high"])) <= tolerance and _is_bearish(current):
            patterns.add("tweezer_top")

    if prior and previous:
        if _is_bearish(prior) and _candle_body(previous) <= _candle_range(previous) * 0.35 and _is_bullish(current):
            if _safe_float(current["close"]) > (_safe_float(prior["open"]) + _safe_float(prior["close"])) / 2.0:
                patterns.add("morning_star")

        if _is_bullish(prior) and _candle_body(previous) <= _candle_range(previous) * 0.35 and _is_bearish(current):
            if _safe_float(current["close"]) < (_safe_float(prior["open"]) + _safe_float(prior["close"])) / 2.0:
                patterns.add("evening_star")

        if all(_is_bullish(candles[i]) for i in (index - 2, index - 1, index)):
            if _safe_float(candles[index - 2]["close"]) < _safe_float(candles[index - 1]["close"]) < _safe_float(current["close"]):
                patterns.add("three_white_soldiers")

        if all(_is_bearish(candles[i]) for i in (index - 2, index - 1, index)):
            if _safe_float(candles[index - 2]["close"]) > _safe_float(candles[index - 1]["close"]) > _safe_float(current["close"]):
                patterns.add("three_black_crows")

        first_low = _safe_float(candles[index - 2]["low"])
        current_low = _safe_float(current["low"])
        middle_high = _safe_float(previous["high"])
        if (
            abs(first_low - current_low) <= tolerance
            and middle_high > max(first_low, current_low) + tolerance
        ):
            patterns.add("double_bottom")

        first_high = _safe_float(candles[index - 2]["high"])
        current_high = _safe_float(current["high"])
        middle_low = _safe_float(previous["low"])
        if (
            abs(first_high - current_high) <= tolerance
            and middle_low < min(first_high, current_high) - tolerance
        ):
            patterns.add("double_top")

    if candle_range > 0 and body <= candle_range * 0.1:
        patterns.add("doji")

    if lower_wick >= body * 2 and upper_wick <= max(body, candle_range * 0.15):
        patterns.add("bullish_pin_bar")
        if _preceding_trend(candles, index) == "down":
            patterns.add("hammer")

    if upper_wick >= body * 2 and lower_wick <= max(body, candle_range * 0.15):
        patterns.add("bearish_pin_bar")
        preceding_trend = _preceding_trend(candles, index)
        if preceding_trend == "up":
            patterns.add("shooting_star")
        elif preceding_trend == "down":
            patterns.add("inverted_hammer")

    if candle_range > 0 and body / candle_range >= 0.85:
        if _is_bullish(current):
            patterns.add("bullish_marubozu")
        if _is_bearish(current):
            patterns.add("bearish_marubozu")

    if candle_range > 0 and body / candle_range >= 0.7:
        if _is_bullish(current) and upper_wick <= candle_range * 0.15:
            patterns.add("strong_breakout_candle")
        if _is_bearish(current) and lower_wick <= candle_range * 0.15:
            patterns.add("strong_breakdown_candle")

    return patterns


def _confirmation_type_matches(candles, index, ctype):
    candle = candles[index]
    patterns = detect_candlestick_patterns(candles, index)

    if ctype == "bullish":
        return _is_bullish(candle) or bool(patterns & BULLISH_PATTERNS)

    if ctype == "bearish":
        return _is_bearish(candle) or bool(patterns & BEARISH_PATTERNS)

    if ctype == "strong_bullish":
        return (
            _is_bullish(candle)
            and _candle_body(candle) > _candle_range(candle) * 0.6
        ) or bool(patterns & STRONG_BULLISH_PATTERNS)

    if ctype == "strong_bearish":
        return (
            _is_bearish(candle)
            and _candle_body(candle) > _candle_range(candle) * 0.6
        ) or bool(patterns & STRONG_BEARISH_PATTERNS)

    return False


# =========================================================
# TOUCH DETECTION (INDICATORS)
# =========================================================

def _body_bounds(candle):
    return (
        min(_safe_float(candle["open"]), _safe_float(candle["close"])),
        max(_safe_float(candle["open"]), _safe_float(candle["close"])),
    )


def _touch_reference_value(lower_tol, upper_tol):
    return (_safe_float(lower_tol) + _safe_float(upper_tol)) / 2.0


def _body_touch_matches(candle, lower_tol, upper_tol, direction=None):
    if any(key not in candle for key in ("open", "close")):
        return False

    body_low, body_high = _body_bounds(candle)
    overlaps = body_low <= upper_tol and body_high >= lower_tol

    if not overlaps:
        return False

    reference_value = _touch_reference_value(lower_tol, upper_tol)

    if direction == "up":
        return body_high <= reference_value

    if direction == "down":
        return body_low >= reference_value

    return True


def _wick_touch_matches(candle, lower_tol, upper_tol, direction=None):
    if any(key not in candle for key in ("low", "high")):
        return False

    low = _safe_float(candle["low"])
    high = _safe_float(candle["high"])

    if direction not in {"up", "down"}:
        return low <= upper_tol and high >= lower_tol

    if any(key not in candle for key in ("open", "close")):
        return low <= upper_tol and high >= lower_tol

    body_low, body_high = _body_bounds(candle)
    reference_value = _touch_reference_value(lower_tol, upper_tol)

    upper_wick_intersects = (
        high > body_high
        and high >= lower_tol
        and body_high <= reference_value
    )
    lower_wick_intersects = (
        low < body_low
        and low <= upper_tol
        and body_low >= reference_value
    )

    if direction == "up":
        return upper_wick_intersects

    return lower_wick_intersects


def detect_touch(candle, lower_tol, upper_tol, config, direction=None):

    touch_type = config.get("touch_type", "wick")

    if touch_type == "wick":
        return _wick_touch_matches(candle, lower_tol, upper_tol, direction)

    if touch_type == "body":
        return _body_touch_matches(candle, lower_tol, upper_tol, direction)

    if touch_type == "both":
        wick = _wick_touch_matches(candle, lower_tol, upper_tol, direction)
        body = _body_touch_matches(candle, lower_tol, upper_tol, direction)
        return wick or body

    return False


# =========================================================
# SERIES DIRECTION
# =========================================================

def series_direction_matches(series, idx, direction, epsilon=1e-9):

    if not direction:
        return True

    if idx < 0 or idx >= len(series):
        return False

    if direction in {"rising", "falling"}:
        if idx - 1 < 0:
            return False

        delta = float(series[idx]) - float(series[idx - 1])

        if direction == "rising":
            return delta > epsilon

        return delta < -epsilon

    if direction in {"turning_up", "turning_down"}:
        if idx - 2 < 0:
            return False

        previous_delta = float(series[idx - 1]) - float(series[idx - 2])
        current_delta = float(series[idx]) - float(series[idx - 1])

        if direction == "turning_up":
            return previous_delta <= epsilon and current_delta > epsilon

        return previous_delta >= -epsilon and current_delta < -epsilon

    return False


# =========================================================
# CONFIRMATION
# =========================================================

def _is_confirmable_candle(candle):
    if candle.get("is_closed") is False:
        return False
    if candle.get("is_complete") is False:
        return False
    if candle.get("complete") is False:
        return False
    if candle.get("closed") is False:
        return False
    if candle.get("is_live") is True:
        return False

    return True


def confirm_if_needed(candles, index, config):

    if not config.get("confirmation", False):
        return True

    window = int(config.get("confirmation_window", 1) or 1)
    confirmation_type = config.get("confirmation_type")
    confirmation_types = config.get("confirmation_types") or []
    confirmation_patterns = config.get("confirmation_patterns") or []

    if confirmation_type and confirmation_type not in confirmation_types:
        confirmation_types = [confirmation_type, *confirmation_types]

    if not confirmation_types and not confirmation_patterns:
        return True

    for i in range(0, window + 1):

        if index + i >= len(candles):
            break

        candle_index = index + i
        candle = candles[candle_index]

        if not _is_confirmable_candle(candle):
            continue

        for ctype in confirmation_types:
            if _confirmation_type_matches(candles, candle_index, ctype):
                return True

        if confirmation_patterns:
            patterns = detect_candlestick_patterns(candles, candle_index)
            if any(pattern in patterns for pattern in confirmation_patterns):
                return True

    return False
