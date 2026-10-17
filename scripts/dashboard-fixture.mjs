/** Shared required filter and coverage fields for synthetic dashboard checks. */
export const filterFixture = (changes = {}) => ({ range: 'all', project_id: '', model: '', source_id: '', provider: '', start: '', end: '', ...changes });
export function coverageFixture(state = 'complete') {
  return { conflicts: 0, parse_errors: 0, replay_tokens: 0, unresolved: 0,
    tokens: { state, sessions: 1, recorded_sessions: state === 'unavailable' ? 0 : 1,
      reasoning: state === 'complete' ? 'recorded' : state,
      metrics: Object.fromEntries(['total', 'input', 'cached', 'writes', 'output', 'reasoning'].map(key =>
        [key, { state, available: state === 'unavailable' ? 0 : 1, observations: state === 'partial' ? 2 : 1 }])) } };
}
