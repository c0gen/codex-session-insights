import type { Source } from './types';
import { esc } from './ui';

export function sourceIndexHealth(source: Source): string {
  const h = source.index_health;
  if (!h) return '';
  const parts = [h.discovered_at == null ? 'Waiting for source verification' : `Files checked ${new Date(h.discovered_at * 1000).toLocaleString()}`];
  if (h.error) parts.push(h.error === 'source_offline' ? 'Source offline: reconnect it and refresh' : 'Source discovery failed: check folder access and refresh');
  if (h.pending_files) parts.push(`${h.pending_files} files waiting for indexing`);
  if (h.file_errors) parts.push(`${h.file_errors} file errors; Refresh retries them`);
  if (h.parse_gaps) parts.push(`${h.parse_gaps} files contain incomplete or unreadable records`);
  if (h.next_retry_at != null) parts.push(`Automatic retry ${new Date(h.next_retry_at * 1000).toLocaleTimeString()}`);
  return `<p class="fine-print source-index-health">${esc(parts.join(' · '))}.</p>`;
}
