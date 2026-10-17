"""Strict sanitized v3 legacy provenance and nullable component validation."""
from uuid import UUID

from .accounting import COMPONENTS
from .keys import DECODER_VERSION, READER_SHA256


def validate_legacy(fact):
    provenance = fact.get('provenance')
    if not isinstance(provenance, dict) or set(provenance) != {'format','decoder','reader_sha256','authenticated','index_matched','trajectory_id'}:
        raise ValueError('Invalid legacy provenance')
    if provenance['format'] != 'antigravity_legacy' or provenance['decoder'] != DECODER_VERSION or provenance['reader_sha256'] != READER_SHA256 or provenance['authenticated'] is not True or type(provenance['index_matched']) is not bool:
        raise ValueError('Unsupported legacy decoder provenance')
    if str(UUID(provenance['trajectory_id'])) != provenance['trajectory_id']:
        raise ValueError('Invalid trajectory identity')
    if fact['provider'] != 'antigravity' or fact.get('snapshot_mode') != 'complete_binary' or fact['proofs']:
        raise ValueError('Invalid legacy snapshot format')
    coverage = fact.get('coverage')
    if not isinstance(coverage, dict) or set(coverage) != set(COMPONENTS) | {'edits','edit_completion_time'}:
        raise ValueError('Invalid component coverage')
    for name, value in coverage.items():
        if not isinstance(value, dict) or set(value) != {'available','observations'} or any(type(v) is not int or v < 0 for v in value.values()) or value['available'] > value['observations']:
            raise ValueError('Invalid component coverage counts')
        if name not in ('edits', 'edit_completion_time'):
            trace = fact['raw_token_trace']
            if value['observations'] != len(trace) or value['available'] != sum(e['last_usage'][name] is not None for e in trace):
                raise ValueError('Component coverage disagrees with facts')
    for event in fact['raw_token_trace']:
        if set(event['last_usage']) != set(COMPONENTS):
            raise ValueError('Incomplete legacy component schema')
        usage = event['last_usage']
        if usage['input_tokens'] is not None and usage['cached_input_tokens'] is not None and usage['cached_input_tokens'] > usage['input_tokens']:
            raise ValueError('Invalid legacy cache subset')
        if usage['output_tokens'] is not None and usage['reasoning_output_tokens'] is not None and usage['reasoning_output_tokens'] > usage['output_tokens']:
            raise ValueError('Invalid legacy reasoning subset')
        if usage['total_tokens'] is not None and (usage['input_tokens'] is None or usage['output_tokens'] is None or usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']):
            raise ValueError('Invalid legacy total')
        components = event.get('recorded_components')
        if not isinstance(components, dict) or set(components) != {'noncached_input_tokens','response_output_tokens'} or any(v is not None and (type(v) is not int or v < 0) for v in components.values()):
            raise ValueError('Invalid recorded component schema')
    relationships = fact.get('subagent_relationships')
    if not isinstance(relationships, list):
        raise ValueError('Invalid subagent relationships')
    from ...codec import timestamp
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {'id','parent_session_id','timestamp','step_count'} or relationship['parent_session_id'] != fact['id'] or not timestamp(relationship['timestamp']) or type(relationship['step_count']) is not int or relationship['step_count'] < 0:
            raise ValueError('Invalid subagent relationship fields')
        if not relationship['id'].startswith('antigravity:') or str(UUID(relationship['id'][12:])) != relationship['id'][12:]:
            raise ValueError('Invalid subagent identity')
