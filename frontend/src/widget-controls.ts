import { call } from "./api";
import { canRefreshAccount, type WidgetAccount } from "./widget-accounts";

export class WidgetRefreshControls {
  readonly pending = new Set<string>();
  readonly errors = new Map<string, string>();
  private failedAt = new Map<string, number | null>();
  private allPending = false;

  constructor(private list: () => WidgetAccount[], private render: () => void,
    private poll: () => Promise<void>, private status: (message: string, failed?: boolean) => void) {}

  reconcile() {
    for (const account of this.list()) {
      const failedAt = this.failedAt.get(account.id);
      if (failedAt !== undefined && account.allowance.last_success_at !== null &&
        account.allowance.last_success_at > (failedAt ?? -1)) {
        this.errors.delete(account.id);
        this.failedAt.delete(account.id);
      }
    }
  }

  busy() { return this.allPending; }

  async refresh(id: string, poll = true) {
    const account = this.list().find(a => a.id === id);
    if (!account || !canRefreshAccount(account) || account.allowance.refreshing || this.pending.has(id)) return;
    this.pending.add(id);
    this.errors.delete(id);
    this.failedAt.delete(id);
    this.render();
    try {
      await call("account_refresh", { id });
      if (poll) await this.poll();
    } catch {
      this.errors.set(id, "Could not refresh this account. Try Refresh again.");
      this.failedAt.set(id, account.allowance.last_success_at);
      this.status(`Could not refresh ${account.label}`, true);
    } finally {
      this.pending.delete(id);
      this.render();
    }
  }

  async refreshAll() {
    if (this.allPending) return;
    this.allPending = true;
    this.render();
    try {
      const ids = [...new Set(this.list().filter(canRefreshAccount).map(a => a.id))];
      await Promise.allSettled(ids.map(id => this.refresh(id, false)));
      // Reread local snapshots without manufacturing a new reception time.
      await this.poll();
      if (this.errors.size) this.status("Some accounts could not be refreshed", true);
    } finally {
      this.allPending = false;
      this.render();
    }
  }
}
