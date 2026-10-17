"""Authenticated complete binary snapshot decoding, with no plaintext persistence."""
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .discovery import LegacyError
from .schema import validate
from .wire import message

HISTORICAL_CONFIG_FIELDS = {("exa.cortex_pb.CascadeToolConfig", n) for n in (24, 26, 27)}


def decode(data, key, conversation_id):
    if len(data) < 28:
        raise LegacyError("truncated_ciphertext")
    try:
        plaintext = AESGCM(bytes(key)).decrypt(data[:12], data[12:], None)
    except InvalidTag:
        # Authentication cannot distinguish a wrong key from damaged ciphertext.
        raise LegacyError("archive_authentication_failed") from None
    try:
        unknown = set(validate(plaintext))
        if unknown - HISTORICAL_CONFIG_FIELDS:
            raise LegacyError("unsupported_trajectory_fields")
        trajectory = message(plaintext)
        if trajectory.get(6) != [conversation_id.encode("ascii")]:
            raise LegacyError("conversation_identity_mismatch")
        if len(trajectory.get(1, [])) != 1 or not trajectory.get(2):
            raise LegacyError("incomplete_trajectory")
        return trajectory
    finally:
        del plaintext
