# services/confluence.py

from services.utils import build_indicator_sticker, detect_touch


LEGACY_ROLE_REVERSAL = "role_reversal"


def apply_confluence(data, config):

    filtered = []
    raw_type = str(getattr(config, "type", "bullish") or "bullish").strip().lower()

    for asset in data:

        channels = asset.get("confluence_channels") or asset.get("channels")
        candles = asset.get("candles")

        if not channels or not candles:
            continue

        if evaluate_confluence(candles, channels, config):
            lookback = _normalized_lookback(getattr(config, "lookback_candles", 4))
            source_count = len(_iter_channel_sources(channels, config))
            condition = _confluence_condition(raw_type, source_count, lookback)
            asset.setdefault("stickers", []).append(
                build_indicator_sticker(
                    "Confluence",
                    condition,
                    {
                        "window": lookback,
                        "confirmation": False,
                    },
                    window=lookback,
                    decision=_confluence_decision(raw_type),
                )
            )
            asset.setdefault("matched_indicators", []).append("confluence")
            filtered.append(asset)

    return filtered


def evaluate_confluence_detail(asset, config):
    if not config:
        return None

    channels = asset.get("confluence_channels") or asset.get("channels")
    candles = asset.get("candles")
    raw_type = str(getattr(config, "type", "bullish") or "bullish").strip().lower()
    lookback = _normalized_lookback(getattr(config, "lookback_candles", 4))
    source_channels = _iter_channel_sources(channels or {}, config)

    details = {
        "type": raw_type,
        "lookback_candles": lookback,
        "liquidity_sweep": bool(getattr(config, "liquidity_sweep", False)),
        "tolerance_pct": abs(float(getattr(config, "tolerance_pct", 0.1) or 0.1)),
        "source_ids": [source["source_id"] for source in source_channels],
        "source_count": len(source_channels),
        "selections": [
            {
                "source_id": source["source_id"],
                "channel_type": source["channel_type"],
                "selection": source["selection"],
            }
            for source in source_channels
        ],
    }

    if not candles or not channels:
        return {
            "name": "confluence",
            "passed": False,
            "summary": "Missing candles or channel data.",
            "details": details,
        }

    passed = evaluate_confluence(candles, channels, config)
    summary = _confluence_condition(raw_type, len(source_channels), lookback)
    sticker = build_indicator_sticker(
        "Confluence",
        summary,
        {
            "window": lookback,
            "confirmation": False,
        },
        window=lookback,
        decision=_confluence_decision(raw_type),
    )
    return {
        "name": "confluence",
        "passed": passed,
        "summary": summary if passed else f"{summary} not detected.",
        "sticker": sticker if passed else None,
        "details": details,
    }


def supported_confluence_selections(channel_type):
    normalized = str(channel_type or "").strip().lower()
    if normalized == "trend":
        return (
            "top_line",
            "middle_line",
            "bottom_line",
            "top_zone",
            "bottom_zone",
        )

    return (
        "upper",
        "middle",
        "lower",
    )


def default_confluence_selection(channel_type, confluence_type="bullish", source_index=0):
    normalized_channel_type = str(channel_type or "").strip().lower()
    raw_type = str(confluence_type or "bullish").strip().lower()
    normalized_type = normalize_confluence_type(confluence_type)

    if raw_type == LEGACY_ROLE_REVERSAL and source_index == 1:
        return "bottom_line" if normalized_channel_type == "trend" else "lower"

    if normalized_type == "bullish":
        return "bottom_line" if normalized_channel_type == "trend" else "lower"

    if normalized_type == "any" and source_index == 0:
        return "bottom_line" if normalized_channel_type == "trend" else "lower"

    return "top_line" if normalized_channel_type == "trend" else "upper"


def normalize_confluence_selection(
    channel_type,
    selection,
    confluence_type="bullish",
    source_index=0,
):
    normalized_channel_type = str(channel_type or "").strip().lower()
    normalized_selection = str(selection or "").strip().lower()
    valid = set(supported_confluence_selections(normalized_channel_type))

    if normalized_channel_type == "trend":
        aliases = {
            "top": "top_line",
            "upper": "top_line",
            "upper_line": "top_line",
            "middle": "middle_line",
            "center": "middle_line",
            "bottom": "bottom_line",
            "lower": "bottom_line",
            "lower_line": "bottom_line",
        }
        normalized_selection = aliases.get(normalized_selection, normalized_selection)
    else:
        aliases = {
            "top": "upper",
            "top_line": "upper",
            "bottom": "lower",
            "bottom_line": "lower",
            "center": "middle",
            "middle_line": "middle",
        }
        normalized_selection = aliases.get(normalized_selection, normalized_selection)

    if normalized_selection in valid:
        return normalized_selection

    return default_confluence_selection(
        normalized_channel_type,
        confluence_type=confluence_type,
        source_index=source_index,
    )


def normalize_confluence_type(confluence_type):
    normalized = str(confluence_type or "").strip().lower()
    if normalized in {"bullish", "bearish", "breakout", "any", LEGACY_ROLE_REVERSAL}:
        return normalized
    return "bullish"


def _confluence_decision(confluence_type):
    normalized = normalize_confluence_type(confluence_type)

    if normalized == "bullish":
        return "Bullish Confluence"
    if normalized == "bearish":
        return "Bearish Confluence"
    if normalized == "breakout":
        return "Breakout Confluence"
    if normalized == LEGACY_ROLE_REVERSAL:
        return "Role Reversal"
    return "Channel Confluence"


def _confluence_condition(confluence_type, source_count, lookback):
    label = "Role Reversal" if confluence_type == LEGACY_ROLE_REVERSAL else str(confluence_type).replace("_", " ").title()
    return f"{label} alignment across {source_count} selected lines/zones in {lookback} candles"


def evaluate_confluence(candles, channels, config):
    raw_type = normalize_confluence_type(getattr(config, "type", "bullish"))
    liquidity_required = bool(getattr(config, "liquidity_sweep", False))
    lookback = _normalized_lookback(getattr(config, "lookback_candles", 4))
    tolerance_pct = abs(float(getattr(config, "tolerance_pct", 0.1) or 0.1))
    source_channels = _iter_channel_sources(channels, config)

    if len(source_channels) != 2:
        return False

    if raw_type == LEGACY_ROLE_REVERSAL:
        matched = _matches_role_reversal(candles, source_channels, lookback, tolerance_pct)
    elif raw_type == "bullish":
        matched = _matches_bullish(candles, source_channels, lookback, tolerance_pct)
    elif raw_type == "bearish":
        matched = _matches_bearish(candles, source_channels, lookback, tolerance_pct)
    elif raw_type == "breakout":
        matched = _matches_breakout(candles, source_channels, lookback, tolerance_pct)
    elif raw_type == "any":
        matched = any(
            (
                _matches_bullish(candles, source_channels, lookback, tolerance_pct),
                _matches_bearish(candles, source_channels, lookback, tolerance_pct),
                _matches_breakout(candles, source_channels, lookback, tolerance_pct),
            )
        )
    else:
        matched = False

    if not matched:
        return False

    if liquidity_required and not detect_liquidity_sweep(candles[-2:]):
        return False

    return True


def _config_value(config, key, default=None):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _normalized_lookback(lookback):
    try:
        parsed = int(lookback)
    except (TypeError, ValueError):
        parsed = 4

    return min(4, max(1, parsed))


def _source_id(source, index):
    channel_type = _config_value(source, "channel_type") or _config_value(source, "type") or "channel"
    return str(_config_value(source, "id") or f"{channel_type}_{index}")


def _configured_sources(config):
    raw_type = normalize_confluence_type(_config_value(config, "type", "bullish"))
    configured = []

    for index, source in enumerate(_config_value(config, "sources", []) or []):
        channel_type = _config_value(source, "channel_type") or _config_value(source, "type")
        if not channel_type:
            continue

        configured.append(
            {
                "source_id": _source_id(source, index),
                "channel_type": channel_type,
                "selection": normalize_confluence_selection(
                    channel_type,
                    _config_value(source, "selection"),
                    confluence_type=raw_type,
                    source_index=index,
                ),
            }
        )

    if configured:
        return configured[:2]

    for index, channel_type in enumerate(_config_value(config, "channels", []) or []):
        configured.append(
            {
                "source_id": f"{channel_type}_{index}",
                "channel_type": channel_type,
                "selection": default_confluence_selection(
                    channel_type,
                    confluence_type=raw_type,
                    source_index=index,
                ),
            }
        )

    return configured[:2]


def _iter_channel_sources(channels, config):
    if not isinstance(channels, dict):
        return []

    structured = channels and all(
        isinstance(payload, dict) and "channel" in payload
        for payload in channels.values()
    )

    resolved = []
    configured_sources = _configured_sources(config)

    for index, source in enumerate(configured_sources):
        channel_type = source["channel_type"]
        channel = None

        if structured:
            payload = channels.get(source["source_id"])
            if payload:
                channel = payload.get("channel")
                channel_type = payload.get("channel_type") or channel_type
        else:
            channel = channels.get(source["source_id"]) or channels.get(channel_type)

        if not channel:
            continue

        resolved.append(
            {
                "source_id": source["source_id"],
                "channel_type": channel_type,
                "selection": normalize_confluence_selection(
                    channel_type,
                    source.get("selection"),
                    confluence_type=_config_value(config, "type", "bullish"),
                    source_index=index,
                ),
                "channel": channel,
            }
        )

    if resolved:
        return resolved

    if structured:
        fallback = []
        raw_type = _config_value(config, "type", "bullish")
        for index, (source_id, payload) in enumerate(channels.items()):
            channel = payload.get("channel")
            channel_type = payload.get("channel_type")
            if not channel or not channel_type:
                continue
            fallback.append(
                {
                    "source_id": str(source_id),
                    "channel_type": channel_type,
                    "selection": default_confluence_selection(
                        channel_type,
                        confluence_type=raw_type,
                        source_index=index,
                    ),
                    "channel": channel,
                }
            )
        return fallback[:2]

    return []


def _recent_indices(candles, lookback):
    latest_index = len(candles) - 1
    start_index = max(0, latest_index - lookback + 1)
    return range(latest_index, start_index - 1, -1)


def _candidate_first_indices(second_index):
    return range(max(0, second_index - 3), second_index + 1)


def _bars_inclusive(start_index, end_index):
    return max(0, end_index - start_index + 1)


def _selection_tolerance(snapshot, tolerance_pct):
    base = max(abs(snapshot["mid"]), 1.0)
    return base * (abs(float(tolerance_pct or 0.0)) / 100.0)


def _selection_midpoint(first_source, second_source, candles, candle_index):
    first_snapshot = _selection_snapshot(first_source, candles, candle_index)
    second_snapshot = _selection_snapshot(second_source, candles, candle_index)
    if not first_snapshot or not second_snapshot:
        return None, None
    return first_snapshot, second_snapshot


def _holds_support(candles, source, candle_index, tolerance_pct):
    snapshot = _selection_snapshot(source, candles, candle_index)
    candle = candles[candle_index]
    if not snapshot:
        return False

    tolerance = _selection_tolerance(snapshot, tolerance_pct)
    return detect_touch(
        candle,
        snapshot["lower"] - tolerance,
        snapshot["upper"] + tolerance,
        {"touch_type": "both"},
        direction="down",
    )


def _holds_resistance(candles, source, candle_index, tolerance_pct):
    snapshot = _selection_snapshot(source, candles, candle_index)
    candle = candles[candle_index]
    if not snapshot:
        return False

    tolerance = _selection_tolerance(snapshot, tolerance_pct)
    return detect_touch(
        candle,
        snapshot["lower"] - tolerance,
        snapshot["upper"] + tolerance,
        {"touch_type": "both"},
        direction="up",
    )


def _breaks_resistance(candles, source, candle_index):
    if candle_index <= 0:
        return False

    previous_close = _candle_value(candles[candle_index - 1], "close")
    current_close = _candle_value(candles[candle_index], "close")
    previous_snapshot = _selection_snapshot(source, candles, candle_index - 1)
    current_snapshot = _selection_snapshot(source, candles, candle_index)

    if (
        previous_close is None
        or current_close is None
        or previous_snapshot is None
        or current_snapshot is None
    ):
        return False

    return previous_close <= previous_snapshot["upper"] and current_close > current_snapshot["upper"]


def _close_above_selection(candles, source, candle_index):
    close_value = _candle_value(candles[candle_index], "close")
    snapshot = _selection_snapshot(source, candles, candle_index)
    if close_value is None or snapshot is None:
        return False
    return close_value > snapshot["upper"]


def _close_below_selection(candles, source, candle_index):
    close_value = _candle_value(candles[candle_index], "close")
    snapshot = _selection_snapshot(source, candles, candle_index)
    if close_value is None or snapshot is None:
        return False
    return close_value < snapshot["lower"]


def _close_not_below_selection(candles, source, candle_index):
    close_value = _candle_value(candles[candle_index], "close")
    snapshot = _selection_snapshot(source, candles, candle_index)
    if close_value is None or snapshot is None:
        return False
    return close_value >= snapshot["lower"]


def _active_close_run(candles, source, start_index, relation):
    count = 0
    started = False

    for candle_index in range(start_index, len(candles)):
        matched = _close_above_selection(candles, source, candle_index)
        if relation == "below":
            matched = _close_below_selection(candles, source, candle_index)

        if matched:
            started = True
            count += 1
            continue

        if started:
            return None

    return count if started else None


def _all_closes_above_from(candles, source, start_index):
    return all(
        _close_above_selection(candles, source, candle_index)
        for candle_index in range(start_index, len(candles))
    )


def _all_closes_not_below(candles, source, start_index, end_index):
    if end_index < start_index:
        return True

    return all(
        _close_not_below_selection(candles, source, candle_index)
        for candle_index in range(start_index, end_index + 1)
    )


def _latest_close_near_support(candles, source, tolerance_pct):
    latest_index = len(candles) - 1
    close_value = _candle_value(candles[latest_index], "close")
    snapshot = _selection_snapshot(source, candles, latest_index)
    if close_value is None or snapshot is None:
        return False

    tolerance = _selection_tolerance(snapshot, tolerance_pct)
    return close_value >= snapshot["lower"] and close_value <= snapshot["upper"] + tolerance


def _latest_close_below_first(candles, source):
    latest_index = len(candles) - 1
    return _close_below_selection(candles, source, latest_index)


def _latest_close_at_or_below_first(candles, source, tolerance_pct):
    latest_index = len(candles) - 1
    close_value = _candle_value(candles[latest_index], "close")
    snapshot = _selection_snapshot(source, candles, latest_index)
    if close_value is None or snapshot is None:
        return False

    tolerance = _selection_tolerance(snapshot, tolerance_pct)
    return close_value <= snapshot["upper"] + tolerance


def _selection_is_below(first_source, second_source, candles, candle_index):
    first_snapshot, second_snapshot = _selection_midpoint(first_source, second_source, candles, candle_index)
    if not first_snapshot or not second_snapshot:
        return False
    return second_snapshot["mid"] < first_snapshot["mid"]


def _selection_is_above(first_source, second_source, candles, candle_index):
    first_snapshot, second_snapshot = _selection_midpoint(first_source, second_source, candles, candle_index)
    if not first_snapshot or not second_snapshot:
        return False
    return second_snapshot["mid"] > first_snapshot["mid"]


def _selection_is_clustered(first_source, second_source, candles, candle_index, tolerance_pct):
    first_snapshot, second_snapshot = _selection_midpoint(first_source, second_source, candles, candle_index)
    if not first_snapshot or not second_snapshot:
        return False

    base = max(abs(first_snapshot["mid"]), abs(second_snapshot["mid"]), 1.0)
    threshold = max(base * (abs(float(tolerance_pct or 0.0)) / 100.0), 1e-9)
    return abs(first_snapshot["mid"] - second_snapshot["mid"]) <= threshold


def _matches_breakout(candles, source_channels, lookback, tolerance_pct):
    first_source, second_source = source_channels
    latest_index = len(candles) - 1

    for second_index in _recent_indices(candles, lookback):
        if _breaks_resistance(candles, second_source, second_index):
            close_run = _active_close_run(candles, second_source, second_index, "above")
            if close_run is not None and 1 <= close_run <= 4:
                for first_index in _candidate_first_indices(second_index):
                    if _breaks_resistance(candles, first_source, first_index):
                        if _bars_inclusive(first_index, latest_index) > 4:
                            continue
                        return True

            close_run = _active_close_run(candles, second_source, second_index, "above")
            if close_run is not None and 1 <= close_run <= 3:
                for first_index in _candidate_first_indices(second_index):
                    if _holds_support(candles, first_source, first_index, tolerance_pct):
                        if _bars_inclusive(first_index, latest_index) > 4:
                            continue
                        return True

        if not _holds_support(candles, second_source, second_index, tolerance_pct):
            continue

        if not _latest_close_near_support(candles, second_source, tolerance_pct):
            continue

        for first_index in _candidate_first_indices(second_index):
            if not _breaks_resistance(candles, first_source, first_index):
                continue

            if _bars_inclusive(first_index, latest_index) > 4:
                continue

            if not _all_closes_above_from(candles, first_source, first_index):
                continue

            return True

    return False


def _matches_role_reversal(candles, source_channels, lookback, tolerance_pct):
    first_source, second_source = source_channels
    latest_index = len(candles) - 1

    for second_index in _recent_indices(candles, lookback):
        if not _holds_support(candles, second_source, second_index, tolerance_pct):
            continue

        if not _latest_close_near_support(candles, second_source, tolerance_pct):
            continue

        for first_index in _candidate_first_indices(second_index):
            if not _breaks_resistance(candles, first_source, first_index):
                continue

            if _bars_inclusive(first_index, latest_index) > 4:
                continue

            if not _all_closes_above_from(candles, first_source, first_index):
                continue

            return True

    return False


def _matches_bullish(candles, source_channels, lookback, tolerance_pct):
    first_source, second_source = source_channels
    latest_index = len(candles) - 1

    for second_index in _recent_indices(candles, lookback):
        if not _holds_support(candles, second_source, second_index, tolerance_pct):
            continue

        dual_support_run = _active_close_run(candles, second_source, second_index, "above")
        if dual_support_run is not None and 1 <= dual_support_run <= 4:
            for first_index in _candidate_first_indices(second_index):
                if _holds_support(candles, first_source, first_index, tolerance_pct):
                    if _bars_inclusive(first_index, latest_index) > 4:
                        continue
                    return True

        if not _selection_is_below(first_source, second_source, candles, second_index):
            continue

        if not _latest_close_near_support(candles, second_source, tolerance_pct):
            continue

        for first_index in _candidate_first_indices(second_index):
            if not _holds_support(candles, first_source, first_index, tolerance_pct):
                continue

            if _bars_inclusive(first_index, latest_index) > 4:
                continue

            if not _all_closes_not_below(candles, first_source, first_index, second_index - 1):
                continue

            if not _all_closes_not_below(candles, second_source, second_index, latest_index):
                continue

            return True

    return False


def _matches_bearish(candles, source_channels, lookback, tolerance_pct):
    first_source, second_source = source_channels
    latest_index = len(candles) - 1

    for second_index in _recent_indices(candles, lookback):
        if not _holds_resistance(candles, second_source, second_index, tolerance_pct):
            continue

        if _selection_is_above(first_source, second_source, candles, second_index):
            for first_index in _candidate_first_indices(second_index):
                if not _holds_resistance(candles, first_source, first_index, tolerance_pct):
                    continue

                if _bars_inclusive(first_index, latest_index) > 4:
                    continue

                if _latest_close_below_first(candles, first_source):
                    return True

        if not _selection_is_clustered(first_source, second_source, candles, second_index, tolerance_pct):
            continue

        close_run = _active_close_run(candles, first_source, second_index, "below")
        if close_run is None or close_run > 4:
            continue

        if not _latest_close_at_or_below_first(candles, first_source, tolerance_pct):
            continue

        for first_index in _candidate_first_indices(second_index):
            if _holds_resistance(candles, first_source, first_index, tolerance_pct):
                if _bars_inclusive(first_index, latest_index) > 4:
                    continue
                return True

    return False


def _selection_snapshot(source, candles, candle_index):
    channel = source.get("channel") or {}
    channel_type = str(source.get("channel_type") or "").strip().lower()
    selection = normalize_confluence_selection(
        channel_type,
        source.get("selection"),
        source_index=0,
    )
    line_index = _line_index_for_candle(channel, len(candles), candle_index)

    if line_index is None:
        return None

    if channel_type == "trend":
        if selection == "top_line":
            value = _line_value(channel, line_index, "top")
            if value is None:
                return None
            lower = upper = value
        elif selection == "middle_line":
            value = _line_value(channel, line_index, "middle")
            if value is None:
                return None
            lower = upper = value
        elif selection == "bottom_line":
            value = _line_value(channel, line_index, "bottom")
            if value is None:
                return None
            lower = upper = value
        elif selection == "top_zone":
            lower = _line_value(channel, line_index, "top_zone_lower")
            upper = _line_value(channel, line_index, "top_zone_upper")
        elif selection == "bottom_zone":
            lower = _line_value(channel, line_index, "bottom_zone_lower")
            upper = _line_value(channel, line_index, "bottom_zone_upper")
        else:
            return None
    else:
        series_name = selection if selection in {"upper", "middle", "lower"} else "lower"
        value = _line_value(channel, line_index, series_name)
        if value is None:
            return None
        lower = upper = value

    if lower is None or upper is None:
        return None

    ordered_lower = min(lower, upper)
    ordered_upper = max(lower, upper)
    return {
        "selection": selection,
        "lower": ordered_lower,
        "upper": ordered_upper,
        "mid": (ordered_lower + ordered_upper) / 2.0,
    }


def _channel_line(channel, *names):
    for name in names:
        value = channel.get(name)
        if value is not None:
            return value
    return None


def get_channel_area(channel, candles, candle_index, tolerance_pct, source_id="channel"):
    del tolerance_pct

    line_index = _line_index_for_candle(channel, len(candles), candle_index)
    if line_index is None:
        return None

    boundaries = []

    lower_val = _line_value(channel, line_index, "lower", "bottom")
    if lower_val is not None:
        boundaries.append(
            {
                "source_id": source_id,
                "role": "lower",
                "value": lower_val,
            }
        )

    upper_val = _line_value(channel, line_index, "upper", "top")
    if upper_val is not None:
        boundaries.append(
            {
                "source_id": source_id,
                "role": "upper",
                "value": upper_val,
            }
        )

    if not boundaries:
        return None

    return {
        "source_id": source_id,
        "boundaries": boundaries,
    }


def _line_index_for_candle(channel, candle_count, candle_index):
    upper = _channel_line(
        channel,
        "upper",
        "top",
        "middle",
        "lower",
        "bottom",
        "top_zone_upper",
        "top_zone_lower",
        "bottom_zone_upper",
        "bottom_zone_lower",
    )
    lower = _channel_line(channel, "lower", "bottom")
    available_lengths = [
        len(series)
        for series in (upper, lower)
        if series is not None and len(series) > 0
    ]

    if not available_lengths:
        return None

    line_count = min(candle_count, max(available_lengths))
    line_index = line_count - (candle_count - candle_index)

    if line_index < 0:
        return None

    return line_index


def _line_value(channel, line_index, *names):
    series = _channel_line(channel, *names)
    if series is None or line_index >= len(series):
        return None

    try:
        value = series[line_index]
    except (IndexError, TypeError):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candle_value(candle, key):
    try:
        return float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None


def detect_liquidity_sweep(candles):

    if len(candles) < 2:
        return False

    last = candles[-1]
    prev = candles[-2]

    if last["low"] < prev["low"] and last["close"] > prev["low"]:
        return True

    if last["high"] > prev["high"] and last["close"] < prev["high"]:
        return True

    return False
