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
  day: string;
  tokens: number;
  cost: number;
  prompts: number;
  lines: number;
}
export interface Project {
  project_id: string;
  name: string;
  chats: number;
  tokens: number;
  cost: number;
  added: number;
  removed: number;
  last_active: string;
}
export interface Source {
  id: string;
  label: string;
  kind: string;
  root: string | null;
  enabled: number;
  status: string;
  updated: string | null;
  detail: string;
  segments: number;
  revision: number;
}
export interface Job {
  running: boolean;
  message: string;
  error: string | null;
  progress: {
    sessions?: number;
    phase?: string;
    files?: number;
    changed_files?: number;
    bytes_read?: number;
    source?: string;
  };
  revision?: number;
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
  summary: Summary;
  timeline: Day[];
  projects: Project[];
  models: { name: string; tokens: number; cost: number }[];
  heatmap: { weekday: number; hour: number; count: number }[];
  tiers: { name: string; responses: number; tokens: number }[];
  efforts: { name: string; responses: number }[];
  agents: { name: string; sessions: number; tokens: number }[];
  highlights: { busiest: Day | null; expensive: Day | null; milestone: number };
  equivalents: { total: Equivalents; output: Equivalents };
  options: { projects: { id: string; name: string }[]; models: string[] };
  sources: Source[];
  timezone: string;
  revision: number;
  generated_at: string;
  demo: boolean;
  exporter: boolean;
  coverage: {
    conflicts: number;
    parse_errors: number;
    replay_tokens: number;
    unresolved: number;
  };
  settings: { device_label: string; assumed_fast_percent: number };
  job: Job;
  readonly?: boolean;
}
export interface Filters {
  range: string;
  project_id: string;
  model: string;
  source_id: string;
  start: string;
  end: string;
}
export interface Dashboard {
  filters?: Filters;
}
declare global {
  interface Window {
    pywebview?: {
      api: { call: (action: string, args: unknown) => Promise<unknown> };
    };
    __INSIGHTS_REPORT__?: Dashboard;
  }
}
