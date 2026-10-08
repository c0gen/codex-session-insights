"""Response accounting shared by ingestion, lineage reconciliation and audits.

Pinned reference: tibotattle 297b12ef, providers/codex/log-parser.js.
Provider totals are authoritative; cache reads/writes and reasoning are subsets.
"""
from collections import Counter

TOKEN_USAGE_KEYS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)


def empty_usage():
    return dict.fromkeys(TOKEN_USAGE_KEYS, 0)


def normalize_usage(value):
    if not isinstance(value, dict):
        return None
    result = empty_usage()
    for key in TOKEN_USAGE_KEYS:
        try:
            result[key] = max(int(value.get(key, 0) or 0), 0)
        except (TypeError, ValueError, OverflowError):
            pass
    return result


def add_usage(total, value):
    value = normalize_usage(value) or empty_usage()
    for key in TOKEN_USAGE_KEYS:
        total[key] = total.get(key, 0) + value[key]
    return total


def subtract_usage(current, previous):
    current = normalize_usage(current)
    previous = normalize_usage(previous) or empty_usage()
    if current is None or current["total_tokens"] < previous["total_tokens"]:
        return None
    return {key: max(current[key] - previous[key], 0) for key in TOKEN_USAGE_KEYS}


def usage_signature(value):
    normalized = normalize_usage(value) or empty_usage()
    return tuple(normalized[key] for key in TOKEN_USAGE_KEYS)


class TokenUsageAccumulator:
    def __init__(self, baseline=None):
        self.previous = normalize_usage(baseline)
        self.reanchored = False
        self.adjustments = Counter()

    def consume(self, cumulative, last=None):
        current, last = normalize_usage(cumulative), normalize_usage(last)
        if current is None:
            self.adjustments["last_only_events"] += bool(last)
            return last or empty_usage()
        previous = self.previous
        self.previous = current
        if previous is None:
            self.adjustments["initial_events"] += 1
            if last is not None:
                self.adjustments["initial_baseline_tokens_omitted"] += max(current["total_tokens"] - last["total_tokens"], 0)
            return last if last is not None else current
        difference = current["total_tokens"] - previous["total_tokens"]
        if difference == 0:
            self.adjustments["duplicate_snapshots"] += 1
            return empty_usage()
        if difference < 0:
            self.reanchored = True
            self.adjustments["counter_regressions"] += 1
            if last is None:
                self.adjustments["regressions_without_response"] += 1
            else:
                self.adjustments["reset_response_tokens_recovered"] += last["total_tokens"]
            return last or empty_usage()
        delta = subtract_usage(current, previous)
        use_last = last is not None and (self.reanchored or difference > last["total_tokens"] + 16)
        self.reanchored = False
        if use_last:
            self.adjustments["response_replacements"] += 1
            self.adjustments["positive_jump_tokens_removed"] += max(difference - last["total_tokens"], 0)
            self.adjustments["positive_jump_tokens_recovered"] += max(last["total_tokens"] - difference, 0)
            return last
        return delta
