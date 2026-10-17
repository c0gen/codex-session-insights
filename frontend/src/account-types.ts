import type { BurnRateEstimate, UsageLimits } from "./types";

export interface ResetCredit {
  id: string;
  title: string;
  status: "available" | "redeeming" | "redeemed" | "unknown";
  granted_at: number | null;
  expires_at: number | null;
  expiration: "dated" | "none" | "unknown";
}
export interface ResetCredits {
  available_count: number | null;
  credits: ResetCredit[] | null;
  details_complete: boolean;
}
export interface AccountHistory {
  enabled: boolean;
  allowed: boolean;
  status: UsageLimits["status"];
  stale: boolean;
  refreshing: boolean;
  last_success_at: number | null;
  error: string | null;
  error_code: string | null;
  summary: {
    lifetime_tokens: number | null;
    peak_daily_tokens: number | null;
    current_streak_days: number | null;
    longest_streak_days: number | null;
    longest_running_turn_sec: number | null;
  };
  daily: { day: string; tokens: number }[] | null;
}
export interface AccountSnapshot {
  provider?: "codex";
  id: string;
  display_id?: string;
  label: string;
  managed: boolean;
  enabled: boolean;
  removing: boolean;
  plan: string | null;
  allowance: UsageLimits;
  history: AccountHistory;
}
export interface AccountLogin {
  status: "idle" | "starting" | "waiting" | "cancelling" | "completed" | "cancelled" | "failed";
  url?: string;
  account_id?: string;
  label?: string;
  error?: string | null;
}
export interface AccountsSnapshot {
  allowed: boolean;
  enabled: boolean;
  error: string | null;
  login: AccountLogin;
  accounts: AccountSnapshot[];
  token_total?: AccountTokenTotal;
  token_burn_rate?: BurnRateEstimate;
  cost_burn_rate?: BurnRateEstimate;
}

export interface AccountTokenTotal {
  total_tokens: number | null;
  accounts: number;
  reported_accounts: number;
  identity_complete: boolean;
  unresolved_connections: number;
  stale: boolean;
  refreshing: boolean;
  last_success_at: number | null;
}
