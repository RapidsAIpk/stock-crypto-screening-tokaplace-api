# services/channel_respect.py

from services.utils import build_indicator_sticker, detect_touch, humanize_token

# =========================================================
# APPLY CHANNEL RESPECT
# =========================================================

def apply_channel_respect(data, config):

    filtered = []

    channel_type = config.channel_type
    min_respect = config.min_respect
    max_respect = config.max_respect

    for asset in data:

        candles = asset.get("candles")
        channels = asset.get("channels")

        if not candles or not channels:
            continue

        channel = channels.get(channel_type)

        if not channel:
            continue

        respect_count = count_respects(
            candles,
            channel,
            config
        )

        if min_respect is not None and respect_count < min_respect:
            continue

        if max_respect is not None and respect_count > max_respect:
            continue

        condition = _channel_respect_condition(channel_type, config.line, respect_count)
        asset.setdefault("stickers", []).append(
            build_indicator_sticker(
                "Channel Respect",
                condition,
                {
                    "window": len(candles),
                    "confirmation": False,
                },
                window=len(candles),
                decision=_channel_respect_decision(config.line),
            )
        )
        asset.setdefault("matched_indicators", []).append("channel_respect")

        filtered.append(asset)

    return filtered


def evaluate_channel_respect_detail(asset, config):
    if not config:
        return None

    candles = asset.get("candles")
    channels = asset.get("channels")
    channel_type = getattr(config, "channel_type", None)
    line = getattr(config, "line", "middle")

    details = {
        "channel_type": channel_type,
        "line": line,
        "min_respect": getattr(config, "min_respect", None),
        "max_respect": getattr(config, "max_respect", None),
        "tolerance_pct": getattr(config, "tolerance_pct", 0.0),
        "cluster_gap": getattr(config, "cluster_gap", 3),
        "touch_type": getattr(config, "touch_type", "wick"),
    }

    if not candles or not channels:
        return {
            "name": "channel_respect",
            "passed": False,
            "summary": "Missing candles or channel data.",
            "details": details,
        }

    channel = channels.get(channel_type)
    if not channel:
        return {
            "name": "channel_respect",
            "passed": False,
            "summary": f"{humanize_token(channel_type)} channel not available.",
            "details": details,
        }

    respect_count, counted_respect_indexes, matched_candle_indexes = count_respects_with_evidence(
        candles,
        channel,
        config,
    )
    passed = True
    min_respect = getattr(config, "min_respect", None)
    max_respect = getattr(config, "max_respect", None)

    if min_respect is not None and respect_count < min_respect:
        passed = False

    if max_respect is not None and respect_count > max_respect:
        passed = False

    condition = _channel_respect_condition(channel_type, line, respect_count)
    sticker = build_indicator_sticker(
        "Channel Respect",
        condition,
        {
            "window": len(candles),
            "confirmation": False,
        },
        window=len(candles),
        decision=_channel_respect_decision(line),
    )
    details["respect_count"] = respect_count
    details["counted_respect_candle_indexes"] = counted_respect_indexes
    details["counted_respect_candle_times"] = [
        candles[index].get("time")
        for index in counted_respect_indexes
        if 0 <= index < len(candles) and candles[index].get("time") is not None
    ]
    details["matched_candle_indexes"] = matched_candle_indexes
    details["matched_candle_times"] = [
        candles[index].get("time")
        for index in matched_candle_indexes
        if 0 <= index < len(candles) and candles[index].get("time") is not None
    ]
    return {
        "name": "channel_respect",
        "passed": passed,
        "summary": condition,
        "sticker": sticker,
        "details": details,
    }


# =========================================================
# COUNT RESPECTS
# =========================================================

def count_respects(candles, channel, config):
    respects, _, _ = count_respects_with_evidence(candles, channel, config)
    return respects


def count_respects_with_evidence(candles, channel, config):

    line_names = normalize_line_names(config.line, channel)
    tolerance_pct = config.tolerance_pct
    cluster_gap = _normalize_cluster_gap(getattr(config, "cluster_gap", 3))
    touch_config = {"touch_type": getattr(config, "touch_type", "wick")}

    counted_respect_indexes = []
    matched_candle_indexes = []
    respect_count = 0
    for line_name in line_names:
        line = channel.get(line_name)
        if line is None:
            continue
        line_respect_indexes, line_touch_indexes = _respect_evidence_for_line(
            candles,
            line,
            tolerance_pct=tolerance_pct,
            cluster_gap=cluster_gap,
            touch_config=touch_config,
        )
        respect_count += len(line_respect_indexes)
        counted_respect_indexes.extend(line_respect_indexes)
        matched_candle_indexes.extend(line_touch_indexes)

    counted_respect_indexes = sorted(set(counted_respect_indexes))
    matched_candle_indexes = sorted(set(matched_candle_indexes))
    return respect_count, counted_respect_indexes, matched_candle_indexes


def _channel_respect_condition(channel_type, line, respect_count):
    return f"{humanize_token(channel_type)} {humanize_token(line)} respected {respect_count} times"


def _channel_respect_decision(line):
    normalized = str(line or "").strip().lower()

    if normalized in {"lower", "lower_middle"}:
        return "Support Proven"
    if normalized == "upper":
        return "Resistance Proven"
    if normalized == "upper_middle":
        return "Upper Structure Proven"
    if normalized in {"both", "all"}:
        return "Channel Respect Match"
    return "Structure Respect Match"


def _respect_evidence_for_line(candles, line, tolerance_pct, cluster_gap, touch_config):
    respect_indexes = []
    touch_indexes = []
    last_touch_index = None
    separated_since_last_touch = False

    max_index = min(len(candles), len(line))
    candle_offset = len(candles) - max_index

    for i in range(max_index):
        candle_index = candle_offset + i
        candle = candles[candle_index]
        line_value = line[i]

        if line_value is None:
            continue

        if detect_channel_touch(candle, line_value, tolerance_pct, touch_config):
            touch_indexes.append(candle_index)
            if last_touch_index is None:
                respect_indexes.append(candle_index)
            elif candle_index - last_touch_index > cluster_gap and separated_since_last_touch:
                respect_indexes.append(candle_index)
            last_touch_index = candle_index
            separated_since_last_touch = False
            continue

        if last_touch_index is None:
            continue

        if _has_distinct_separation(candle, line_value, tolerance_pct, touch_config):
            separated_since_last_touch = True

    return respect_indexes, touch_indexes


def normalize_line_names(line_name, channel):
    has_top = "top" in channel
    has_bottom = "bottom" in channel
    upper_name = "top" if has_top else "upper"
    lower_name = "bottom" if has_bottom else "lower"

    if line_name == "upper":
        return [upper_name]
    if line_name == "lower":
        return [lower_name]
    if line_name == "both":
        return [upper_name, lower_name]
    if line_name == "upper_middle":
        return [upper_name, "middle"]
    if line_name == "lower_middle":
        return [lower_name, "middle"]
    if line_name == "all":
        return [upper_name, "middle", lower_name]
    return ["middle"]


def detect_channel_touch(candle, line_value, tolerance_pct, touch_config=None, touch_direction=None):

    tolerance = _touch_tolerance(line_value, tolerance_pct)
    upper = line_value + tolerance
    lower = line_value - tolerance
    return detect_touch(
        candle,
        lower,
        upper,
        touch_config or {"touch_type": "wick"},
        direction=touch_direction,
    )


def _normalize_cluster_gap(cluster_gap):
    try:
        gap = int(cluster_gap)
    except (TypeError, ValueError):
        gap = 3

    return min(5, max(3, gap))


def _touch_tolerance(line_value, tolerance_pct):
    return abs(float(line_value)) * (abs(float(tolerance_pct or 0)) / 100.0)


def _has_distinct_separation(candle, line_value, tolerance_pct, touch_config, touch_direction=None):
    if detect_channel_touch(candle, line_value, tolerance_pct, touch_config, touch_direction):
        return False

    separation = max(_touch_tolerance(line_value, tolerance_pct) * 2.0, abs(float(line_value)) * 0.001, 1e-6)

    if "close" in candle and abs(float(candle["close"]) - float(line_value)) >= separation:
        return True

    if "open" in candle and abs(float(candle["open"]) - float(line_value)) >= separation:
        return True

    if "high" in candle and "low" in candle:
        midpoint = (float(candle["high"]) + float(candle["low"])) / 2.0
        return abs(midpoint - float(line_value)) >= separation

    return False
