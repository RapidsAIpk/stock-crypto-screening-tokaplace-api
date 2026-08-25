"""Shared inclusive range and selection-mode utilities for scanner rules."""


def normalize_non_negative_int(value, default=None):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def normalize_range(min_value=None, max_value=None):
    minimum = normalize_non_negative_int(min_value, None)
    maximum = normalize_non_negative_int(max_value, None)
    if minimum is not None and maximum is not None and maximum < minimum:
        return minimum, maximum, False
    return minimum, maximum, True


def candles_since_in_range(event_index, current_index, min_value=None, max_value=None):
    if event_index is None or current_index is None:
        return False
    minimum, maximum, valid = normalize_range(min_value, max_value)
    if not valid:
        return False
    candles_since = int(current_index) - int(event_index)
    if candles_since < 0:
        return False
    if minimum is not None and candles_since < minimum:
        return False
    if maximum is not None and candles_since > maximum:
        return False
    return True


def consecutive_count_in_range(count, min_value=None, max_value=None):
    minimum, maximum, valid = normalize_range(min_value, max_value)
    if not valid:
        return False
    normalized_count = normalize_non_negative_int(count, 0)
    if minimum is not None and normalized_count < minimum:
        return False
    if maximum is not None and normalized_count > maximum:
        return False
    return True


def selection_mode_pass(results, mode="all"):
    values = [bool(value) for value in results]
    if not values:
        return False

    normalized = str(mode or "all").strip().lower()
    passed_count = sum(1 for value in values if value)

    if normalized == "any":
        return passed_count >= 1
    if normalized == "one":
        return passed_count == 1
    if normalized == "multiple":
        return passed_count >= 2
    return passed_count == len(values)
