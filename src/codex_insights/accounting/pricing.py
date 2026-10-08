#!/usr/bin/env python3
"""Pricing helpers for Codex session token accounting."""
from __future__ import annotations

from datetime import date, datetime, timezone

LONG_CONTEXT_INPUT_THRESHOLD = 272_000

SERVICE_TIER_ALIASES = {
    "auto": None,
    "default": "standard",
    "standard": "standard",
    "fast": "priority",
    "priority": "priority",
    "flex": "flex",
}
SERVICE_TIER_LABELS = {
    "standard": "Standard",
    "flex": "Flex",
    "priority": "Fast / Priority",
    "unobserved": "Not logged",
    "unknown": "Unknown",
}
SERVICE_TIER_ORDER = ["priority", "flex", "standard", "unobserved", "unknown"]


def _rate(input_cost, cached_input, output_cost, pricing_model):
    return {
        "input": input_cost,
        "cached_input": cached_input,
        "output": output_cost,
        "pricing_model": pricing_model,
        **({"cache_write": input_cost * 1.25} if pricing_model.startswith(("gpt-5.6", "gpt-6")) else {}),
    }


def _date(value):
    return date.fromisoformat(value) if value else None


GPT_5_6_RELEASE_DATE = _date("2026-07-09")
GPT_5_6_TERRA_LUNA_PRICE_CHANGE_DATE = _date("2026-07-30")
GPT_5_6_FAST_LONG_CONTEXT_DATE = _date("2026-08-05")
GPT_5_6_SOL_PRICE_CHANGE_DATE = _date("2026-08-21")
GPT_6_ASTRA_RELEASE_DATE = _date("2026-09-03")


def _tiered_rates(
    model_name,
    input_cost,
    cached_input_cost,
    output_cost,
    *,
    fast_long_context=False,
):
    """Build standard, Flex, Fast, and long-context rates for a model."""
    flex_input = input_cost / 2
    flex_cached_input = cached_input_cost / 2
    flex_output = output_cost / 2
    priority_rates = _rate(
        input_cost * 2,
        cached_input_cost * 2,
        output_cost * 2,
        f"{model_name} priority",
    )
    if fast_long_context:
        priority_rates["long_context"] = _rate(
            input_cost * 4,
            cached_input_cost * 4,
            output_cost * 3,
            f"{model_name} priority",
        )
    return {
        **_rate(input_cost, cached_input_cost, output_cost, model_name),
        "long_context": _rate(
            input_cost * 2,
            cached_input_cost * 2,
            output_cost * 1.5,
            model_name,
        ),
        "service_tiers": {
            "flex": {
                **_rate(flex_input, flex_cached_input, flex_output, f"{model_name} flex"),
                "long_context": _rate(
                    flex_input * 2,
                    flex_cached_input * 2,
                    flex_output * 1.5,
                    f"{model_name} flex",
                ),
            },
            "priority": priority_rates,
        },
    }


def _tiered_rate_record(
    model_name,
    start,
    end,
    input_cost,
    cached_input_cost,
    output_cost,
    *,
    fast_long_context=False,
    effective_note="",
):
    note = (
        "Direct API price from OpenAI API Pricing. Requests above 272K input tokens use long-context "
        "rates for the full request. Logged Fast service tier maps to API Fast/Priority pricing where "
        "supported. Cache writes have a separate 1.25x uncached-input API rate, when published; observed cache writes are an input subset."
    )
    if effective_note:
        note = f"{note} {effective_note}"
    return {
        "start": start,
        "end": end,
        "rates": _tiered_rates(
            model_name,
            input_cost,
            cached_input_cost,
            output_cost,
            fast_long_context=fast_long_context,
        ),
        "note": note,
    }


def _gpt_5_6_sol_rate_records():
    return [
        _tiered_rate_record(
            "gpt-5.6-sol",
            GPT_5_6_RELEASE_DATE,
            GPT_5_6_FAST_LONG_CONTEXT_DATE,
            5.00,
            0.50,
            30.00,
            effective_note="GPT-5.6 Sol launch pricing.",
        ),
        _tiered_rate_record(
            "gpt-5.6-sol",
            GPT_5_6_FAST_LONG_CONTEXT_DATE,
            GPT_5_6_SOL_PRICE_CHANGE_DATE,
            5.00,
            0.50,
            30.00,
            fast_long_context=True,
            effective_note="GPT-5.6 Sol launch pricing; long-context Fast rates available from August 5, 2026.",
        ),
        _tiered_rate_record(
            "gpt-5.6-sol",
            GPT_5_6_SOL_PRICE_CHANGE_DATE,
            None,
            4.00,
            0.40,
            20.00,
            fast_long_context=True,
            effective_note="GPT-5.6 Sol promotional pricing effective August 21, 2026.",
        ),
    ]


def _gpt_5_6_terra_or_luna_rate_records(model_name, launch_rates, current_rates):
    return [
        _tiered_rate_record(
            model_name,
            GPT_5_6_RELEASE_DATE,
            GPT_5_6_TERRA_LUNA_PRICE_CHANGE_DATE,
            *launch_rates,
            effective_note=f"{model_name} launch pricing.",
        ),
        _tiered_rate_record(
            model_name,
            GPT_5_6_TERRA_LUNA_PRICE_CHANGE_DATE,
            GPT_5_6_FAST_LONG_CONTEXT_DATE,
            *current_rates,
            effective_note=f"{model_name} reduced pricing effective July 30, 2026.",
        ),
        _tiered_rate_record(
            model_name,
            GPT_5_6_FAST_LONG_CONTEXT_DATE,
            None,
            *current_rates,
            fast_long_context=True,
            effective_note=(
                f"{model_name} reduced pricing effective July 30, 2026; long-context Fast rates available "
                "from August 5, 2026."
            ),
        ),
    ]


MODEL_RATE_RECORDS = {
    "gpt-6-sol": [_tiered_rate_record("gpt-6-sol", _date("2026-09-22"), None, 2, .20, 10, fast_long_context=True)],
    "gpt-6.1-sol": [_tiered_rate_record("gpt-6.1-sol", _date("2026-09-29"), None, 2, .10, 10, fast_long_context=True)],
    "gpt-6-luna": [_tiered_rate_record("gpt-6-luna", _date("2026-09-22"), None, .10, .01, .50, fast_long_context=True)],
    # The unsuffixed API alias routes to Sol. Keeping it explicit also prices
    # Codex logs that record the alias instead of the resolved model ID.
    "gpt-6-astra": [
        _tiered_rate_record(
            "gpt-6-astra",
            GPT_6_ASTRA_RELEASE_DATE,
            None,
            10.00,
            1.00,
            50.00,
            fast_long_context=True,
            effective_note="GPT-6 Astra pricing effective September 3, 2026.",
        )
    ],
    "gpt-5.6": _gpt_5_6_sol_rate_records(),
    "gpt-5.6-sol": _gpt_5_6_sol_rate_records(),
    "gpt-5.6-terra": _gpt_5_6_terra_or_luna_rate_records(
        "gpt-5.6-terra",
        (2.50, 0.25, 15.00),
        (2.00, 0.20, 12.00),
    ),
    "gpt-5.6-luna": _gpt_5_6_terra_or_luna_rate_records(
        "gpt-5.6-luna",
        (1.00, 0.10, 6.00),
        (0.20, 0.02, 1.20),
    ),
    "gpt-5.5": [
        {
            "start": _date("2026-04-23"),
            "end": None,
            "rates": {
                **_rate(5.00, 0.50, 30.00, "gpt-5.5"),
                "long_context": _rate(10.00, 1.00, 45.00, "gpt-5.5"),
                "service_tiers": {
                    "flex": {
                        **_rate(2.50, 0.25, 15.00, "gpt-5.5 flex"),
                        "long_context": _rate(5.00, 0.50, 22.50, "gpt-5.5 flex"),
                    },
                    "priority": _rate(12.50, 1.25, 75.00, "gpt-5.5 priority"),
                },
            },
            "note": (
                "Direct API price from OpenAI API Pricing. Sessions above 272K input tokens use GPT-5.5 "
                "long-context rates for the full request. Logged Fast service tier maps to API priority "
                "pricing where supported."
            ),
        }
    ],
    "gpt-5.4": [
        {
            "start": _date("2026-03-05"),
            "end": None,
            "rates": {
                **_rate(2.50, 0.25, 15.00, "gpt-5.4"),
                "long_context": _rate(5.00, 0.50, 22.50, "gpt-5.4"),
                "service_tiers": {
                    "flex": {
                        **_rate(1.25, 0.13, 7.50, "gpt-5.4 flex"),
                        "long_context": _rate(2.50, 0.25, 11.25, "gpt-5.4 flex"),
                    },
                    "priority": _rate(5.00, 0.50, 30.00, "gpt-5.4 priority"),
                },
            },
            "note": (
                "Direct API price from OpenAI API Pricing. Sessions above 272K input tokens use GPT-5.4 "
                "long-context rates for the full request. Logged Fast service tier maps to API priority "
                "pricing where supported."
            ),
        }
    ],
    "gpt-5.4-mini": [
        {
            "start": _date("2026-03-05"),
            "end": None,
            "rates": {
                **_rate(0.75, 0.075, 4.50, "gpt-5.4-mini"),
                "service_tiers": {
                    "flex": _rate(0.375, 0.0375, 2.25, "gpt-5.4-mini flex"),
                    "priority": _rate(1.50, 0.15, 9.00, "gpt-5.4-mini priority"),
                },
            },
            "note": (
                "Direct API price from OpenAI API Pricing. Logged Fast service tier maps to API priority "
                "pricing where supported."
            ),
        }
    ],
    "gpt-5.2": [
        {
            "start": _date("2025-12-11"),
            "end": None,
            "rates": {
                **_rate(1.75, 0.175, 14.00, "gpt-5.2"),
                "service_tiers": {
                    "flex": _rate(0.875, 0.0875, 7.00, "gpt-5.2 flex"),
                    "priority": _rate(3.50, 0.35, 28.00, "gpt-5.2 priority"),
                },
            },
            "note": (
                "Direct API price from OpenAI API Pricing. Logged Fast service tier maps to API priority "
                "pricing where supported."
            ),
        }
    ],
    "gpt-5.2-codex": [
        {
            "start": _date("2026-02-04"),
            "end": _date("2026-02-06"),
            "rates": _rate(1.75, 0.175, 14.00, "gpt-5.2-codex"),
            "note": (
                "Historical official OpenAI API pricing from the February 10, 2026 archived developer pricing page; "
                "current official docs no longer list this price."
            ),
        }
    ],
    "gpt-5.3-codex": [
        {
            "start": _date("2026-02-07"),
            "end": None,
            "rates": {
                **_rate(1.75, 0.175, 14.00, "gpt-5.3-codex"),
                "service_tiers": {
                    "priority": _rate(3.50, 0.35, 28.00, "gpt-5.3-codex priority"),
                },
            },
            "note": (
                "Direct API price from OpenAI API Pricing specialized-model rates. Logged Fast service tier maps "
                "to API priority pricing where supported."
            ),
        }
    ],
    "codex-auto-review": [
        {
            "start": _date("2026-04-23"),
            "end": None,
            "rates": {
                **_rate(2.50, 0.25, 15.00, "gpt-5.4 auto-review"),
                "long_context": _rate(5.00, 0.50, 22.50, "gpt-5.4 auto-review"),
            },
            "note": (
                "Auto-review uses GPT-5.4 Thinking with low reasoning; priced with GPT-5.4 standard API rates. "
                "No Fast/Priority service tier is inferred for auto-review sessions."
            ),
        }
    ],
}

UNPRICED_MODEL_NOTES = {
    "gpt-5.3-codex-spark": (
        "Current Codex docs describe GPT-5.3-Codex-Spark as a research preview and do not publish an API "
        "token price; left unpriced."
    ),
}

PRICING_SOURCES = [
    {"label": "OpenAI API changelog", "url": "https://developers.openai.com/api/docs/changelog", "models": ["GPT-6 Sol/Luna September 22 and GPT-6.1 Sol September 29 releases"]},
    *[{"label": f"{model} model page", "url": f"https://developers.openai.com/api/docs/models/{model}", "models": [model]} for model in ("gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna")],
    {
        "label": "OpenAI API Pricing",
        "url": "https://developers.openai.com/api/docs/pricing",
        "models": [
            "current standard, Flex, and Fast token rates for GPT-6 Astra; GPT-5.6 Sol, Terra, and Luna; "
            "GPT-5.5; GPT-5.4; GPT-5.4 mini; GPT-5.2; and gpt-5.3-codex"
        ],
    },
    {
        "label": "GPT-6 Astra Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-6-astra",
        "models": ["GPT-6 Astra launch pricing, tier multipliers, and cache-write pricing notes"],
    },
    {
        "label": "GPT-5.6 Sol Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        "models": ["GPT-5.6 Sol long-context multiplier and cache-write pricing notes"],
    },
    {
        "label": "GPT-5.6 Terra Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        "models": ["GPT-5.6 Terra long-context multiplier and cache-write pricing notes"],
    },
    {
        "label": "GPT-5.6 Luna Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        "models": ["GPT-5.6 Luna long-context multiplier and cache-write pricing notes"],
    },
    {
        "label": "OpenAI API Changelog",
        "url": "https://developers.openai.com/api/docs/changelog",
        "models": [
            "GPT-5.6 release and alias mapping; July 30 Terra/Luna reductions; August 5 long-context Fast "
            "availability; August 21 Sol promotional pricing; and September 3 GPT-6 Astra release"
        ],
    },
    {
        "label": "GPT-5.5 Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-5.5",
        "models": ["GPT-5.5 long-context threshold and multiplier notes"],
    },
    {
        "label": "GPT-5.4 Model Page",
        "url": "https://developers.openai.com/api/docs/models/gpt-5.4",
        "models": ["GPT-5.4 long-context threshold and multiplier notes"],
    },
    {
        "label": "Archived OpenAI API Pricing (2026-02-10)",
        "url": "https://web.archive.org/web/20260210041738/https://developers.openai.com/api/docs/pricing",
        "models": ["historical gpt-5.2-codex token rates"],
    },
    {
        "label": "Codex Pricing",
        "url": "https://developers.openai.com/codex/pricing",
        "models": ["Codex credit-rate context and GPT-5.3-Codex-Spark research-preview status"],
    },
    {
        "label": "Codex Speed",
        "url": "https://developers.openai.com/codex/speed",
        "models": ["Fast mode credit multipliers and supported models"],
    },
    {
        "label": "OpenAI Alignment Auto-review",
        "url": "https://alignment.openai.com/auto-review/",
        "models": ["Auto-review GPT-5.4 Thinking low-reasoning mapping"],
    },
]


def normalize_service_tier(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return SERVICE_TIER_ALIASES.get(normalized)


def pricing_context_tier(input_tokens):
    return "long" if input_tokens > LONG_CONTEXT_INPUT_THRESHOLD else "short"


def _coerce_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).date() if parsed.tzinfo else parsed.date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def rate_record_for_model(model_name, at=None):
    records = MODEL_RATE_RECORDS.get(model_name) or []
    if not records:
        return None
    at_date = _coerce_date(at)
    if at_date is None:
        return records[-1]
    for record in records:
        start = record.get("start")
        end = record.get("end")
        if (start is None or at_date >= start) and (end is None or at_date < end):
            return record
    return None


def rate_table_for_context(rate_config, context_tier, service_tier="standard"):
    if not rate_config:
        return None
    if service_tier == "standard":
        rates = rate_config
    else:
        rates = rate_config.get("service_tiers", {}).get(service_tier)
    if not rates:
        return None
    if context_tier == "long":
        long_rates = rates.get("long_context")
        if long_rates:
            return long_rates
        if service_tier == "standard":
            return rates
        return None
    return rates


def standard_context_label(rate_config, context_tier):
    if context_tier == "long" and isinstance(rate_config.get("long_context"), dict):
        return "standard long-context pricing"
    return "standard API pricing"


def model_supports_long_context(model_name, at=None):
    record = rate_record_for_model(model_name, at)
    rates = record.get("rates", {}) if record else {}
    return isinstance(rates.get("long_context"), dict)


def unpriced_model_note(model_name, at=None):
    note = UNPRICED_MODEL_NOTES.get(model_name)
    if note:
        return note
    records = MODEL_RATE_RECORDS.get(model_name) or []
    if records:
        starts = [record.get("start") for record in records if record.get("start")]
        earliest = min(starts) if starts else None
        if earliest:
            return (
                f"No active official API/Codex token price is configured for {model_name} before "
                f"{earliest.isoformat()}; left earlier sessions unpriced."
            )
        return (
            f"No active official API/Codex token price is configured for {model_name} on some logged "
            "session dates; left those sessions unpriced."
        )
    at_date = _coerce_date(at)
    suffix = f" for {at_date.isoformat()}" if at_date else ""
    return f"No official API/Codex token price is configured for {model_name or 'unknown model'}{suffix}; left unpriced."


def _safe_token_int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def estimate_token_cost(
    model_name,
    usage,
    service_tier=None,
    service_tier_logged=False,
    assumed_fast_share=0.0,
    at=None,
    request_input_tokens=None,
):
    record = rate_record_for_model(model_name, at)
    if not record:
        return None
    rate_config = record.get("rates") or {}
    input_tokens = _safe_token_int(usage.get("input_tokens"))
    cached_input_tokens = _safe_token_int(usage.get("cached_input_tokens"))
    output_tokens = _safe_token_int(usage.get("output_tokens"))
    cache_write_tokens = _safe_token_int(usage.get("cache_write_input_tokens"))
    uncached_input_tokens = max(input_tokens - cached_input_tokens - cache_write_tokens, 0)
    requested_service_tier = normalize_service_tier(service_tier)
    priced_service_tier = "standard"
    context_tier = pricing_context_tier(input_tokens if request_input_tokens is None else _safe_token_int(request_input_tokens))
    rates = rate_table_for_context(rate_config, context_tier, "standard") or rate_config
    tier_note = ""
    assumption_applied = False
    assumption_blocked_by_context = False
    assumption_share = max(min(float(assumed_fast_share or 0.0), 1.0), 0.0)

    if requested_service_tier in ("flex", "priority") and service_tier_logged:
        tier_rates = rate_table_for_context(rate_config, context_tier, requested_service_tier)
        if tier_rates:
            rates = tier_rates
            priced_service_tier = requested_service_tier
        elif context_tier == "long":
            tier_label = SERVICE_TIER_LABELS.get(requested_service_tier, requested_service_tier)
            fallback_label = standard_context_label(rate_config, context_tier)
            tier_note = (
                f"Observed {tier_label} service tier, but no published long-context rate is configured for this tier; "
                f"used {fallback_label}."
            )
        else:
            tier_label = SERVICE_TIER_LABELS.get(requested_service_tier, requested_service_tier)
            tier_note = (
                f"Observed {tier_label} service tier, but no configured published rate exists for this model; "
                "used standard API pricing."
            )
    elif not service_tier_logged and 0 < assumption_share <= 1:
        fast_tier_rates = rate_table_for_context(rate_config, context_tier, "priority")
        if fast_tier_rates:
            rates = {
                "input": ((1 - assumption_share) * rates["input"] + assumption_share * fast_tier_rates["input"]),
                "cached_input": (
                    (1 - assumption_share) * rates["cached_input"]
                    + assumption_share * fast_tier_rates["cached_input"]
                ),
                "output": ((1 - assumption_share) * rates["output"] + assumption_share * fast_tier_rates["output"]),
                "cache_write": ((1 - assumption_share) * rates.get("cache_write", rates["input"]) + assumption_share * fast_tier_rates.get("cache_write", fast_tier_rates["input"])),
                "pricing_model": f"{rate_config['pricing_model']} blended fast-assumed",
            }
            priced_service_tier = "assumed"
            assumption_applied = True
        else:
            if context_tier == "long":
                tier_note = (
                    "Assumed Fast/Priority share was not applied to long-context requests; "
                    "published Fast/Priority long-context multipliers are not available."
                )
                assumption_blocked_by_context = True

    usd = (
        (uncached_input_tokens / 1_000_000) * rates["input"]
        + (cached_input_tokens / 1_000_000) * rates["cached_input"]
        + (cache_write_tokens / 1_000_000) * rates.get("cache_write", rates["input"])
        + (output_tokens / 1_000_000) * rates["output"]
    )
    note = record.get("note", "")
    if cache_write_tokens and "cache_write" not in rates:
        note += " Cache-write rate unavailable for this model; used input rate for observed writes."
    if requested_service_tier in ("flex", "priority") and priced_service_tier == requested_service_tier:
        tier_label = SERVICE_TIER_LABELS.get(requested_service_tier, requested_service_tier)
        note = f"{note} Applied {tier_label} API service-tier rates where logged.".strip()
    elif assumption_applied:
        fast_share_pct = int(round(assumption_share * 100))
        note = f"{note} No service tier was logged; assumed {fast_share_pct}% Fast/Priority where published tier rates support it for cost estimation.".strip()
    elif tier_note:
        note = f"{note} {tier_note}".strip()

    return {
        "usd": usd,
        "pricing_model": rates["pricing_model"],
        "rates_per_million": {
            "input": rates["input"],
            "cached_input": rates["cached_input"],
            "output": rates["output"],
            **({"cache_write": rates["cache_write"]} if "cache_write" in rates else {}),
        },
        "note": note,
        "context_tier": context_tier,
        "service_tier": priced_service_tier,
        "requested_service_tier": requested_service_tier,
        "assumption_applied": assumption_applied,
        "assumption_share": assumption_share if assumption_applied else 0.0,
        "assumption_blocked_by_context": assumption_blocked_by_context,
    }
