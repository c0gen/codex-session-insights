import type { AccountsSnapshot, AccountTokenTotal, ResetCredits } from "./account-types";

export interface Summary {
  [key: string]: number | string;
  total_tokens: number;
  cost: number;
  chats: number;
  lines_added: number;
  lines_removed: number;
  priced_percent: number;
  active_days: number;
  current: number;
  longest: number;
  output_tokens: number;
  prompts: number;
  input_tokens: number;
  cached_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  change_coverage: string;
}
export interface Day {
  cost_available?: number;
  day: string;
  tokens: number;
  cost: number;
  prompts: number;
  lines: number;
}
export interface UsageMetrics {
  cache_reuse_percent: number | null;
  reasoning_share_percent: number | null;
  reasoning_share_basis?: {
    reasoning_tokens: number;
    output_tokens: number;
    included_responses: number;
    total_responses: number;
  };
  cache_discount_usd: number | null;
  cache_discount_priced_tokens: number;
  cache_discount_total_tokens: number;
  cache_discount_coverage_percent: number | null;
}
export interface CacheRateDay {
  day: string;
  input_tokens: number;
  cached_tokens: number;
  observations: number;
  input_available: number;
  cached_available: number;
}
export interface DailySessions {
  day: string;
  chats: number;
  subagents: number;
  system_agents: number;
}
export interface Project {
  project_id: string;
  name: string;
  chats: number;
  tokens: number;
  analyzed_tokens?: number | null;
  token_coverage?: string;
  estimated_cost?: number | null;
  cost: number | null;
  added: number;
  removed: number;
  last_active: string;
}
export interface Source {
  id: string;
  label: string;
  provider?: string;
  format?: string;
  legacy_diagnostics?: { archive_count?: number; index_matches?: number; decoder?: string; unlock?: string; diagnostic?: string; counts?: Record<string, number> };
  capabilities?: Record<string, unknown>;
  kind: string;
  last_activity?: string | null;
  root: string | null;
  enabled: number;
  status: string;
  updated: string | null;
  detail: string;
  segments: number;
  revision: number;
  index_health?: { discovered_at: number | null; checked_at: number | null; error: string | null;
    pending_files: number; file_errors: number; parse_gaps: number; next_retry_at: number | null };
}
export interface Job {
  state?: "completed" | "cancelled" | "failed";
  id?: number;
  origin?: "automatic" | "user";
  cancelable?: boolean;
  queued?: { id: number; message: string; origin: "automatic" | "user" }[];
  completed?: JobCompletion[];
  running: boolean;
  message: string;
  error: string | null;
  progress: {
      checked?: number; reused?: number; added?: number; changed?: number; removed?: number; recalculated?: number;
    sessions?: number;
    phase?: string;
    files?: number;
    changed_files?: number;
    bytes_read?: number;
    source?: string;
  };
  revision?: number;
}
export interface JobCompletion {
  id: number;
  origin: "automatic" | "user";
  message: string;
  state: "completed" | "cancelled" | "failed";
  error: string | null;
  result?: { changed_files?: number; errors?: number; refresh?: ExportRefresh; warnings?: string[]; [key: string]: unknown } | null;
}
export interface ExportRefresh {
  files: number;
  changed_files: number;
  bytes_read: number;
  errors: number;
  skipped_errors: number;
  offline_sources: number;
}
export interface ActionResponse {
  status?: "started" | "queued" | "cancelled" | "cancelling" | "stopping" | "unchanged";
  job_id?: number;
  message?: string;
}
export interface Equivalents {
  words: number;
  novels: number;
  pages: number;
  stack_meters: number;
  reading_years: number;
  typing_years: number;
  floppy_disks: number;
}
export interface Dashboard {
  analytics_context?: string;
  cached_at?: string;
  analytics_refreshing?: boolean;
  loaded_view?: string;
  source_states?: Record<string, number>;
  summary: Summary;
  usage_metrics?: UsageMetrics;
  daily_sessions?: DailySessions[];
  cache_rate_timeline?: CacheRateDay[] | null;
  timeline: Day[];
  projects: Project[];
  models: { name: string; tokens: number; cost: number | null }[];
  heatmap: { weekday: number; hour: number; count: number }[];
  tiers: { name: string; responses: number; tokens: number }[];
  efforts: { name: string; responses: number }[];
  agents: { name: string; sessions: number; tokens: number | null }[];
  highlights: { busiest: Day | null; expensive: Day | null; milestone: number };
  equivalents: { total: Equivalents; output: Equivalents };
  options: { projects: { id: string; name: string }[]; models: string[] };
  sources: Source[];
  timezone: string;
  revision: number;
  generated_at: string;
  date_bounds?: { start: string | null; end: string };
  demo: boolean;
  exporter: boolean;
  coverage: {
    tokens?: { state: "complete" | "partial" | "unavailable"; sessions: number; recorded_sessions: number; reasoning?: string; metrics?: Record<string, { state: string; available: number; observations: number }> };
    edit_completion_time_unavailable?: number;
    conflicts: number;
    awaiting_verification?: number;
    identity_issues?: number;
    accounting_overlaps?: number;
    parse_errors: number;
    replay_tokens: number;
    unresolved: number;
  };
  settings: { device_label: string; assumed_fast_percent: number; live_usage_enabled?: boolean; claude_usage_enabled?: boolean; antigravity_usage_enabled?: boolean };
  project_merge?: ProjectMerge | null;
  project_migration_pending?: boolean;
  usage_limits?: UsageLimits;
  account_token_total?: AccountTokenTotal;
  indexed_token_totals?: Partial<Record<"codex" | "claude_code" | "antigravity", IndexedTokenTotal>>;
  job: Job;
  readonly?: boolean;
}
export interface IndexedTokenTotal {
  total_tokens: number | null;
  state: "complete" | "partial" | "unavailable";
  sessions: number;
}
export interface Filters {
  range: string;
  project_id: string;
  model: string;
  source_id: string;
  provider?: string;
  start: string;
  end: string;
}
export interface Dashboard {
  analytics_context?: string;
  filters?: Filters;
  desktop?: DesktopState;
}

export type WidgetMetric = "tokens" | "cost" | "lines" | "chats";
export interface DesktopPreferences {
  tray_enabled: boolean;
  widget_enabled: boolean;
  always_on_top: boolean;
  metrics: WidgetMetric[];
  show_usage_remaining: boolean;
  widget_details_expanded: boolean;
  widget_height_css_px?: number | null;
  usage_remaining_bucket: string;
  widget_account_ids?: string[];
  widget_account_buckets?: Record<string, string>;
}
export interface DesktopState {
  available: boolean;
  preferences?: DesktopPreferences;
  revision?: number;
  tray_active?: boolean;
  error?: string | null;
  settings_request?: number;
  account_request?: { sequence: number; account_id: string } | null;
}
export type WidgetTotals = Pick<Summary, "total_tokens" | "cost" | "chats" | "lines_added" | "lines_removed" | "priced_percent" | "change_coverage"> & {
  token_coverage?: string;
  metric_coverage?: Record<string, { state: string; available: number; observations: number }>;
};
export interface WidgetSummary {
  source_states?: Record<string, number>;
  today: WidgetTotals;
  all_time: WidgetTotals;
  timezone: string;
  date: string;
  revision: number;
  generated_at: string;
  job: Job;
  desktop: DesktopState;
  usage_limits?: UsageLimits;
  accounts?: AccountsSnapshot;
}

export interface ProjectMerge {
  operation_id: string;
  sources: { id: string; name: string }[];
  target: { id: string; name: string };
  sessions: number;
  identities: number;
  completed_at: string;
}
export interface BurnRateEstimate {
  indexing?: { live_checked_at: number | null; live_pending_files: number; historical_pending_files: number;
    oldest_pending_at?: number | null; last_progress_at?: number | null; freshness?: "current" | "updating" | "delayed" };
  value: number | null;
  status: "collecting" | "available" | "stale" | "unavailable";
  observed_seconds: number;
  updated_at: number | null;
  partial?: boolean;
  coverage?: {
    state: "complete" | "partial";
    checked_at: number | null;
    reasons: { code: string; label: string; count: number; source_id?: string; retry_at?: number }[];
    freshness?: { state: "current" | "updating" | "delayed"; sources: {
      source_id: string; source_label?: string; state: string; pending_files: number; pending_projections?: number; oldest_pending_at: number | null;
      pending_age_seconds: number | null; last_progress_at: number | null; checked_at: number | null; overdue_seconds: number;
    }[] };
  };
  detail?: string;
  /** Present on dollar estimates once local usage has been indexed. */
  priced_tokens?: number;
  total_tokens?: number;
}
export interface AllowanceWindow {
  id: string;
  remaining_percent: number | null;
  window_duration_mins: number | null;
  resets_at: number | null;
  burn_rate?: BurnRateEstimate;
}
export interface AllowanceBucket {
  id: string;
  name: string;
  windows: AllowanceWindow[];
}
export interface UsageLimits {
  enabled: boolean;
  allowed: boolean;
  status: "available" | "unavailable" | "stale" | "disabled";
  refreshing: boolean;
  stale: boolean;
  buckets: AllowanceBucket[];
  last_success_at: number | null;
  next_refresh_at: number | null;
  error: string | null;
  error_code: string | null;
  reset_credits?: ResetCredits | null;
  token_burn_rate?: BurnRateEstimate;
  cost_burn_rate?: BurnRateEstimate;
}
declare global {
  interface Window {
    pywebview?: {
      api: { call: (action: string, args: unknown) => Promise<unknown> };
    };
    __INSIGHTS_REPORT__?: Dashboard;
  }
}

export interface ProviderBucket {
  id: string; unit: string; remaining_percent: number | null; used: number | null; limit: number | null; resets_at: number | null; stale?: boolean;
  /** Claude Code /usage rows: the server's meter kind and optional model/surface scope. */
  kind?: string; group?: string | null; scope_label?: string | null; severity?: string | null; is_active?: boolean;
}
/** In-memory official-client /usage check state, independent of which source supplied the buckets. */
export interface ProviderCheck {
  enabled: boolean; allowed: boolean; status: string; refreshing: boolean; error: string | null; error_code: string | null;
  last_success_at: number | null; next_refresh_at: number | null;
}
export interface ProviderAllowance {
  provider: string; label: string; profile: string; source?: string; received_at: number | null;
  status: string; identity_verified: boolean;
  buckets: ProviderBucket[];
  check?: ProviderCheck;
}
export interface ProviderSetup { target: string; status: string; installed?: boolean; upgrade_available?: boolean; error?: string; configuration?: unknown; path?: string }
export interface Dashboard {
  analytics_context?: string; provider_allowances?: ProviderAllowance[]; provider_setup?: ProviderSetup[];
  claude_recovery?: import('./claude-recovery').ClaudeRecovery; }
export interface WidgetSummary { provider_allowances?: ProviderAllowance[]; }
