# Metric review of the previous report

“Slop” here means claims that look precise but cannot be supported by the available logs. A fun conversion with a visible formula is welcome; an unsupported assessment of work quality is not.

| Previous metric/chart | Decision | Reason / replacement |
| --- | --- | --- |
| Total tokens, input/output/cache/reasoning | Keep | Direct counters; show subset relationships and replay handling. |
| API pricing / model and tier comparisons | Keep | Useful estimate with dates, assumptions and priced coverage. |
| Lines added/removed, edit volume | Keep with qualification | Observed confirmed operations, repeated edits count, partial coverage visible. |
| Novels, printed pages, stacked height, reading/typing time, storage equivalents | Keep | Explicit approximations; switch total processed/output only. |
| Daily tokens/cost/prompts/lines | Keep | Readable trend; user chooses the measure. |
| Project and model usage | Keep | Helps explain where usage went; use a table and horizontal bars. |
| Prompt timing heatmap, active days and streaks | Keep | Timestamp facts; no productivity inference. |
| Token milestones, biggest usage/expense day | Keep | Lightweight highlights with directly computable values. |
| Tool counts, effort mix, repeated pie charts | De-emphasize | Facts can be useful for audits, but low value on the home view. Tool names and effort facts remain in the index. |
| Validation / quality / workflow scores | Remove | Keyword matches and arbitrary weights do not measure quality. The previous validation summary gives an empty input a score of 50. |
| Success/failure rates and command outcome assessments | Remove | Logs lack a complete outcome label; keyword rules misclassify normal output. “1 file changed” matched a timeout rule through the substring “hang”. |
| Estimated productivity, efficiency, delegation benefits or time saved | Remove | No reliable human baseline or causal comparison. |
| Environmental/carbon estimates | Remove | Tokens alone cannot establish energy, hardware, utilization or grid emissions. |
| Narrative personality/workflow conclusions and prescriptive advice | Remove | Distracts from this casual usage tool and adds unsupported interpretation. |

## Formula contract

Words = tokens × 0.75; novels = words / 90,000; pages = ceiling(words / 500); stack meters = pages × 0.004 inches × 0.0254; reading years = words / (150 × 60 × 24 × 365.25); typing years uses 60 words/min; 1.44 MB floppy equivalents use 4 bytes/token.

Live Total processed equivalents use the all-time combined headline total: reported Codex lifetime tokens plus enabled indexed Claude Code and Antigravity usage, with the same deduplication, fallback, partial and stale states. Output only uses filtered recorded output because the lifetime total has no output breakdown. Saved reports and demo mode use their analyzed snapshot.

These are text-volume equivalents, not unique authored books, printed output, actual reading time or measured storage. Reasoning is already included in output; cache reads/writes are already included in input. Neither subset is added again to provider total.

Pricing uses [OpenAI’s API price documentation](https://developers.openai.com/api/docs/pricing) and [prompt caching documentation](https://developers.openai.com/api/docs/guides/prompt-caching). The rate catalog supports date boundaries, request input thresholds, logged tiers and explicit assumptions. Unknown model rates never silently become free usage: coverage is shown separately.

## Local dollar burn

`USD/min = sum(priced API-equivalent cost for local Codex usage in (now - 300s, now]) / 5`.
The timestamp window, canonical records, enabled local folder scope, source freshness and partial indexing states are shared with local token burn. Imported snapshots and other providers are excluded; analytics filters and account counters do not affect either rate. Event times prevent old backfills from creating new bursts.

The rate sums projected costs without rounding each response, preserving existing model/date, input, cached-read, cache-write, output, tier, request-context and assumed-Fast pricing. Reasoning is already included in output. Pricing changes rebuild those costs and invalidate the rate cache. Prices are the app's dated catalog or a user-imported catalog, not a live pricing feed. The bundled GPT-6.1 Sol and GPT-6 Astra rates were checked against [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) on October 12, 2026.

Pricing coverage is priced tokens divided by all tokens in the window. Partial coverage shows a labeled subtotal; positive usage with no priced tokens shows Unavailable. A fresh idle window shows $0.00/min with coverage not applicable. A known zero-price catalog entry remains priced. Tiny positive rates show <$0.01/min and retain the exact USD/min in accessible help. A stale index preserves the previous estimate with its original timestamp and pricing coverage. The value estimates token cost only and is not a subscription bill.

## Cache, reasoning and daily sessions

**Usage & Cost** contains three cards and a **Chats and agents per day** chart. They follow the applied date, project, model and canonical source filters in the display timezone. They use analyzed local/imported facts, independently of account lifetime totals and local token burn. Standalone HTML reports retain the same values and chart without network access.

| Metric | Formula and interpretation |
| --- | --- |
| Cache reuse rate | `100 × sum(cached read tokens) / sum(input tokens)`. Input already includes cached reads and writes. |
| Reasoning share | `100 × sum(reasoning tokens) / sum(output tokens)`. Output already includes reasoning. |
| Estimated cache discount | Sum `cached read tokens × (uncached-input rate − cached-input rate) / 1,000,000` for reconciled priced responses, without per-response rounding. |

Ratios use aggregate counters, not averages of response percentages. A positive denominator and zero numerator give 0%; a zero denominator or a subset larger than its denominator gives Unavailable. Original counters remain intact.

The discount uses the exact effective model/date, service tier, request-context threshold and assumed-Fast rates selected by cost accounting. The comparison holds input volume, output and cache-write charges unchanged. It is an API-equivalent estimate, not subscription savings. Signed differences are preserved: a negative value is an estimated surcharge. Tiny amounts remain visible, and the tooltip exposes the unrounded value.

Coverage measures priced cached-read tokens divided by all cached-read tokens. No cached reads means a $0 discount with coverage not applicable. Cached reads with no applicable prices mean Unavailable and 0% coverage. Partial pricing shows only the priced subtotal and explicitly states its cached-token coverage. For example, 1,000,000 input tokens including 600,000 cached reads, 200,000 output including 50,000 reasoning tokens, and input/cache rates of $2/$0.20 per million yield 60% reuse, 25% reasoning share, and a $1.08 estimated discount.

Daily counts are distinct active session IDs in three canonical categories: main chats, spawned sub-agents (including nested agents), and system agents. A session active across several dates counts once on each date. These are not new-chat counts, and summing daily counts does not give the all-range distinct total. Activity does not require positive token usage. Repeated events, copied sources, and multiple segments of one session do not add identities; inherited activity before the session's observed creation boundary is excluded.

Source filters use the selected canonical source, rather than every physical copy. Project filters follow current merged project membership. Model filters use the model recorded with activity; older portable facts can recover it from timestamped event facts, otherwise it remains Unknown. Dates use local calendar boundaries, including DST. The chart fills inactive dates with zero within the inclusive selected range, pages through at most 90 days at a time, and provides a keyboard-accessible exact-count table. An absent observed range has an empty state.

Projection version 2 rebuilds these facts from stored local and imported histories, including offline sources. Lightweight nullable columns allow cached results during deferred GUI maintenance. Before backfill, cached reads lacking price facts remain unpriced; daily counts become available after the projection commits. Records, buckets, projection version and revision update atomically, and a failed upgrade rolls back for retry. Headless queries upgrade before returning. Original logs and transfer snapshots are unchanged; missing historical facts cannot be reconstructed.
