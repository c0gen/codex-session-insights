import { count, esc } from './ui';

interface RecoverySource {
  source_id: string;
  state: string;
  accepted_tokens_before: number;
  accepted_tokens_after?: number;
  accepted_token_change?: number;
  newly_included_tokens?: number;
  reopened_choices?: number;
  unresolved_groups?: number;
  legacy_snapshot_without_alternatives?: boolean;
}

export interface ClaudeRecovery {
  state: string;
  identity_issues: number;
  newly_included_tokens: number;
  newly_included_responses: number;
  reopened_choices: number;
  sources: RecoverySource[];
}

export function recoveryNotice(recovery?: ClaudeRecovery) {
  if (!recovery || recovery.state === 'not_needed') return '';
  const legacy = recovery.sources.some(s => s.legacy_snapshot_without_alternatives);
  return `<section class="panel claude-recovery" aria-label="Claude history recovery"><h2>Claude history recovery</h2><p>${recovery.state === 'running' ? 'Checking stored agent histories. Accepted usage remains available.' : `${count(recovery.newly_included_responses)} newly included responses · ${count(recovery.newly_included_tokens)} newly included tokens.`}</p>${recovery.sources.map(s => `<p class="fine-print">${esc(s.state === 'staging' ? 'Checking history' : s.state === 'pending' ? 'Awaiting verification' : 'Recovery complete')}${s.accepted_tokens_after === undefined ? '' : ` · Accounted Claude tokens across sources: ${count(s.accepted_tokens_before)} → ${count(s.accepted_tokens_after)} (${(s.accepted_token_change || 0) >= 0 ? '+' : ''}${count(s.accepted_token_change || 0)})`}</p>`).join('')}${recovery.identity_issues ? `<p>${count(recovery.identity_issues)} identity observations still need verification. Reconnect the original logs and refresh.</p>` : ''}${recovery.reopened_choices ? `<p>${count(recovery.reopened_choices)} earlier choices were reopened because they covered separate agent histories.</p>` : ''}${legacy ? '<p>This older snapshot omitted alternative histories. Update the Mac exporter, recover its existing index, and import a fresh usage snapshot.</p>' : ''}<p class="fine-print">Conflicting versions can contain the same responses. Their recorded token counters must not be added together.</p></section>`;
}
