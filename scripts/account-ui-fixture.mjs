/** Synthetic account data shared by browser regressions; no sign-in needed. */
export const accountIds = { saved: 'a'.repeat(32), work: 'b'.repeat(32), duplicate: 'c'.repeat(32) };

export function accountFixture(id, label, remaining = 66) {
  const now = Math.floor(Date.now() / 1000);
  const section = { enabled: true, allowed: true, status: 'available', refreshing: false, stale: false,
    last_success_at: now, error: null, error_code: null };
  return { id, label, display_id: id, managed: id !== 'current', enabled: true, removing: false, plan: 'pro',
    allowance: { ...section, next_refresh_at: now + 60, reset_credits: null,
      buckets: ['codex', 'other'].map(bucket => ({ id: bucket, name: bucket === 'codex' ? 'Codex' : 'Other',
        windows: [{ id: 'weekly', remaining_percent: remaining, window_duration_mins: 10080, resets_at: now + 86400 }] })) },
    history: { ...section, summary: { lifetime_tokens: 1000, peak_daily_tokens: 500, current_streak_days: 2,
      longest_streak_days: 2, longest_running_turn_sec: 10 }, daily: [{ day: '2026-10-11', tokens: 500 }, { day: '2026-10-12', tokens: 500 }] } };
}
