import { filterFixture, coverageFixture } from './dashboard-fixture.mjs';
export function metricFixture() {
  const equivalents = { words: 0, novels: 0, pages: 0, stack_meters: 0, reading_years: 0, typing_years: 0, floppy_disks: 0 };
  return {
    summary: { total_tokens: 120, cost: 0.01, chats: 4, lines_added: 0, lines_removed: 0, priced_percent: 100, active_days: 2, current: 0, longest: 1, output_tokens: 20, prompts: 2, input_tokens: 100, cached_tokens: 50, cache_write_tokens: 0, reasoning_tokens: 5, change_coverage: 'no_observed_changes' },
    usage_metrics: { cache_reuse_percent: 50, reasoning_share_percent: 25, cache_discount_usd: 0.0000125, cache_discount_priced_tokens: 25, cache_discount_total_tokens: 50, cache_discount_coverage_percent: 50 },
    daily_sessions: [{ day: '2026-03-07', chats: 4, subagents: 2, system_agents: 1 }, { day: '2026-03-09', chats: 1, subagents: 0, system_agents: 3 }],
    cache_rate_timeline: [{ day: '2026-03-07', input_tokens: 100, cached_tokens: 50, observations: 1, input_available: 1, cached_available: 1 }],
    date_bounds: { start: '2026-03-07', end: '2026-03-10' },
    timeline: [{ day: '2026-03-07', tokens: 120, cost: 0.01, prompts: 2, lines: 0 }],
    projects: [], models: [{ name: 'fixture-model', tokens: 120, cost: 0.01 }], heatmap: [], tiers: [], efforts: [], agents: [],
    highlights: { busiest: null, expensive: null, milestone: 1000 }, equivalents: { total: equivalents, output: equivalents },
    options: { projects: [{ id: 'fixture-project', name: 'Fixture project' }], models: ['fixture-model'] },
    sources: [{ id: 'fixture-source', label: 'Synthetic', enabled: 1, kind: 'import', root: null, status: 'Imported', updated: null, detail: '', segments: 1, revision: 1 }],
    filters: filterFixture(),
    timezone: 'America/New_York', revision: 1, generated_at: '2026-03-11T00:00:00Z', demo: true, exporter: false,
    coverage: coverageFixture(),
    settings: { device_label: 'Synthetic', assumed_fast_percent: 0 }, job: { running: false, message: '', error: null, progress: {} },
  };
}
