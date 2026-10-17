"""Private cache lifecycle identity, separate from proven account identity."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def confirmed_member_identity(account, account_id):
    """Require both workspace and signed-in member before merging connections."""
    # Business members can share the returned accountId. The account/read
    # email distinguishes members; neither it nor the workspace alone proves
    # that two connections share a quota. Missing email stays unresolved.
    email = account.get("email")
    if not isinstance(account_id, str) or not account_id.strip():
        return None
    if not isinstance(email, str) or not email.strip():
        return None
    return fingerprint(["chatgpt-member", account_id, email.strip()])


class AccountIdentity(str):
    """Opaque lifecycle string carrying explicit deduplication evidence."""

    def __new__(cls, lifecycle, confirmed=None):
        value = super().__new__(cls, lifecycle)
        value.confirmed = confirmed
        return value


def confirmed_identity(identity):
    # Strings from older/custom providers are lifecycle markers, not evidence
    # that two connections represent the same member in the same workspace.
    return identity.confirmed if isinstance(identity, AccountIdentity) else None
