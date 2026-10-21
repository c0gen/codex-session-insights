import type { BurnRateEstimate } from './types';
import { esc } from './ui';

/** Both compact and full burn displays use the same reasons and freshness. */
export function burnCoverageHelp(rate: BurnRateEstimate): string {
  const coverage = rate.coverage;
  const reasons = coverage?.reasons.map(r => `${r.label}${r.count > 1 ? ` (${r.count})` : ''}${r.retry_at == null ? '' : `; next retry ${new Date(r.retry_at * 1000).toLocaleTimeString()}`}.`) || [];
  const checked = coverage?.checked_at;
  return [rate.partial ? 'Partial estimate.' : '', ...reasons,
    rate.indexing?.historical_pending_files ? `${rate.indexing.historical_pending_files} verified historical files are being updated in the background.` : '',
    rate.indexing?.live_pending_files ? `${rate.indexing.live_pending_files} files may affect the current five-minute window and are waiting to be indexed.` : '',
    checked == null ? '' : `All included sources checked through ${new Date(checked * 1000).toLocaleString()}.`,
    rate.detail || '', rate.status === 'stale' ? 'Stale: showing the previous estimate.' : '',
  ].filter(Boolean).join(' ');
}

export function burnCoverageMarkup(rate: BurnRateEstimate, id: string): string {
  const labels = [...new Set(rate.coverage?.reasons.map(r => r.label) || [])];
  const badge = rate.partial ? ' <b class="allowance-stale">Partial</b>' : '';
  const stale = rate.status === 'stale' ? ' <b class="allowance-stale">Stale</b>' : '';
  const details = labels.length ? ` <button id="${esc(id)}-coverage" class="text-button burn-coverage" data-burn-sources title="${esc(burnCoverageHelp(rate))}">${esc(labels.join(' · '))}</button>` : '';
  return badge + stale + details;
}
