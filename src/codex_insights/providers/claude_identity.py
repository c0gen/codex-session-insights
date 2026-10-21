"""Portable Claude session identities; paths are evidence, never identity keys."""
import re
from pathlib import Path

from ..codec import digest

PARSER_VERSION = 4
IDENTITY_VERSION = 1


class IdentityError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Claude identity needs verification: ' + reason)


def text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 400 and not any(c in value for c in '/\\\x00') else None


def path_identity(path):
    if path is None:
        return None, None
    path = Path(path)
    agent = text(path.stem[6:]) if path.stem.startswith('agent-') else None
    if not agent:
        return None, None
    for ancestor in path.parents:
        if ancestor.name == 'subagents':
            return text(ancestor.parent.name), agent
    return None, agent


def identity(session, agent=None):
    if not text(session) or agent is not None and not text(agent):
        raise IdentityError('missing_session_or_agent_id')
    suffix = 'subagent:' + digest([session, agent]) if agent else session
    return {'version': IDENTITY_VERSION, 'session_id': session, 'agent_id': agent,
            'id': 'claude_code:' + suffix,
            'parent_session_id': 'claude_code:' + session if agent else None,
            'session_source': 'spawned_subagent' if agent else 'top_level',
            'suffix': suffix}


def resolve(event, path=None, previous=None):
    session = event.get('sessionId') or event.get('session_id') or event.get('conversationId')
    agent = event.get('agentId')
    sidechain = event.get('isSidechain')
    path_parent, path_agent = path_identity(path)
    if session is not None and not text(session) or agent is not None and not text(agent):
        raise IdentityError('invalid_session_or_agent_id')
    if sidechain is not None and type(sidechain) is not bool:
        raise IdentityError('invalid_sidechain_marker')
    explicit_parent = event.get('parentSessionId')
    if explicit_parent is not None and not text(explicit_parent):
        raise IdentityError('invalid_parent_session_id')
    child = sidechain is True or bool(agent or path_agent)
    if sidechain is None and not agent and not path_agent and previous and previous.get('agent_id'):
        child = True
    if sidechain is False and child:
        raise IdentityError('sidechain_marker_disagrees_with_agent')
    if agent and path_agent and agent != path_agent:
        raise IdentityError('agent_metadata_disagrees_with_filename')
    if child:
        agent = agent or path_agent or (previous or {}).get('agent_id')
        parent = explicit_parent or session or path_parent or (previous or {}).get('session_id')
        if path_parent and parent and path_parent != parent:
            raise IdentityError('parent_metadata_disagrees_with_directory')
        result = identity(parent, agent)
    elif session:
        result = identity(session)
    else:
        return previous
    if previous and result['id'] != previous['id']:
        raise IdentityError('multiple_identities_in_one_file')
    return result


def scoped(fact):
    return bool(re.fullmatch(r'claude_code:subagent:[0-9a-f]{64}', fact.get('id', '')))


def cached_identity(fact, path=None, evidence=None):
    """Rekey only structural evidence retained by older parsers, never counters."""
    if evidence:
        return identity(evidence.get('session_id'), evidence.get('agent_id'))
    parent, agent = path_identity(path)
    sid = fact['id'].removeprefix('claude_code:')
    old_parent = fact.get('parent_session_id')
    if old_parent:
        old_parent = old_parent.removeprefix('claude_code:')
    if scoped(fact):
        return None  # Already scoped; its opaque agent digest cannot be reversed.
    if fact.get('session_source') == 'spawned_subagent' and old_parent:
        old_agent = sid[6:] if sid.startswith('agent-') else None
        if agent and old_agent and agent != old_agent or parent and parent != old_parent:
            raise IdentityError('cached_identity_disagrees_with_location')
        return identity(old_parent, old_agent or agent)
    if agent:
        if parent and parent != sid:
            raise IdentityError('cached_parent_disagrees_with_location')
        return identity(sid, agent)
    if path:
        return identity(sid)
    return None


def rekey(fact, resolved, bridge=False):
    if resolved is None:
        return dict(fact)
    return {**fact, **{k: resolved[k] for k in ('id', 'parent_session_id', 'session_source')},
            'segment_id': digest(['claude_code', resolved['suffix'], 'hook' if bridge else 'transcript'])}
