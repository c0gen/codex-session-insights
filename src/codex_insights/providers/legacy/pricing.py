"""Dated launch-rate evidence. Missing cache prices/components stay unpriced."""
from datetime import date

RATES = {
    'claude-sonnet-4-5-20250929': {'start':'2025-09-29', 'end':'2026-03-12', 'input':3.0, 'output':15.0,
        'source':'https://www.anthropic.com/news/claude-sonnet-4-5'},
    'gemini-2.5-flash-lite': {'start':'2025-07-22', 'end':'2026-03-12', 'input':0.1, 'output':0.4,
        'source':'https://developers.googleblog.com/en/gemini-25-flash-lite-is-now-stable-and-generally-available/'},
}


def estimate(item):
    rate, usage = RATES.get(item.get('model')), item['usage']
    if rate is None or not date.fromisoformat(rate['start']) <= item['timestamp'].date() < date.fromisoformat(rate['end']):
        return None
    if any(usage.get(k) is None for k in ('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','total_tokens')):
        return None
    # Launch announcements establish base input/output prices. They do not
    # establish historic cache pricing, durations or long-context surcharges.
    if usage['cached_input_tokens'] != 0 or usage['cache_write_input_tokens'] != 0:
        return None
    if item.get('model','').startswith('claude-') and usage['input_tokens'] > 200000:
        return None
    return {'usd': (usage['input_tokens'] * rate['input'] + usage['output_tokens'] * rate['output']) / 1000000,
        'cache_discount_usd': 0.0}
