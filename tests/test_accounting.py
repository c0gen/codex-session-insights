import pytest
from codex_insights.accounting.token_accounting import TokenUsageAccumulator, empty_usage
from codex_insights.accounting.pricing import estimate_token_cost


def input_usage(n):
    return {**empty_usage(),'input_tokens':n,'total_tokens':n}


def test_reset_and_interleaved_counter_keep_last_response():
    counter=TokenUsageAccumulator()
    assert counter.consume(input_usage(1000),input_usage(20))==input_usage(20)
    assert counter.consume(input_usage(1000),input_usage(20))==empty_usage()
    assert counter.consume(input_usage(100),input_usage(30))==input_usage(30)
    assert counter.consume(input_usage(205),input_usage(20))==input_usage(20)


def test_cache_and_reasoning_subsets_are_not_double_charged():
    usage={**input_usage(1_000_000),'cached_input_tokens':500_000,'output_tokens':100_000,'reasoning_output_tokens':80_000}
    result=estimate_token_cost('gpt-5.3-codex',usage,at='2026-10-01')
    rates=result['rates_per_million']
    expected=.5*rates['input']+.5*rates['cached_input']+.1*rates['output']
    assert result['usd']==pytest.approx(expected)


def test_unknown_model_remains_unpriced():
    assert estimate_token_cost('unknown-model',input_usage(100)) is None
