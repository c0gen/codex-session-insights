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

These are text-volume equivalents, not unique authored books, printed output, actual reading time or measured storage. Reasoning is already included in output; cache reads/writes are already included in input. Neither subset is added again to provider total.

Pricing uses [OpenAI’s API price documentation](https://developers.openai.com/api/docs/pricing) and [prompt caching documentation](https://developers.openai.com/api/docs/guides/prompt-caching). The rate catalog supports date boundaries, request input thresholds, logged tiers and explicit assumptions. Unknown model rates never silently become free usage: coverage is shown separately.
