"""Synthetic fixtures of the authenticated format verified against the reader.

No real archive ciphertext, key, conversation content or profile is embedded.
"""
import base64
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SID = '00000000-0000-4000-8000-000000000001'
TID = '00000000-0000-4000-8000-000000000002'
KEY = b'k' * 32
SECRET = 'PRIVATE_PAYLOAD_DO_NOT_EXPORT'


def v(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def field(number, value):
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return v(number * 8 + 2) + v(len(value)) + value
    return v(number * 8) + v(value)


def msg(*entries):
    return b''.join(field(number, value) for number, value in entries)


TIME = msg((1, 1770000000))
WORKSPACE = msg((1, 'file:///C:/synthetic/project'))


def archive(output=7, reads=100, writes=0, failed=False, include_usage=True, repeated=False, model=330, completion=True, request='verified-request'):
    usage = msg((1, model), (2, 10), (3, output), (9, 2), (10, output - 2), (11, request))
    if reads is not None:
        usage += field(5, reads)
    if writes is not None:
        usage += field(4, writes)
    chat = msg((3, model), (9, msg((4, TIME))))
    if include_usage:
        chat += field(4, usage)
    generator = msg((1, chat), (2, v(1)), (4, 'invocation-identity'))
    if failed:
        generator += field(5, SECRET)
    md = msg((1, TIME), (11, model), (4, msg((1, 'edit-call'), (2, 'replace_file_content'), (3, SECRET))))
    if completion:
        md += field(8, TIME)
    lines = msg((3, msg((1, SECRET), (2, 1))), (3, msg((1, 'removed private content'), (2, 2))))
    result = msg((1, msg((8, 'file:///C:/synthetic/private.txt'), (2, msg((3, lines))))))
    step = msg((1, 5), (4, 7 if failed else 3), (5, md), (10, msg((2, result))))
    user = msg((1, 14), (4, 3), (5, msg((1, TIME))))
    trajectory = msg((1, TID), (6, SID), (2, user), (2, step), (3, generator),
        (7, msg((1, WORKSPACE), (2, TIME))))
    if repeated:
        trajectory += field(3, generator)
    return trajectory


def ciphertext(plaintext, nonce=b'n' * 12):
    return nonce + AESGCM(KEY).encrypt(nonce, plaintext, None)


def profile(path):
    target = Path(path) / 'User/globalStorage'
    target.mkdir(parents=True)
    payload = msg((3, TIME), (7, TIME), (4, TID), (9, WORKSPACE))
    entry = msg((1, SID), (2, msg((1, base64.b64encode(payload)))))
    with sqlite3.connect(target / 'state.vscdb') as db:
        db.execute('CREATE TABLE ItemTable(key TEXT PRIMARY KEY,value TEXT)')
        db.execute('INSERT INTO ItemTable VALUES(?,?)', ('antigravityUnifiedStateSync.trajectorySummaries', base64.b64encode(msg((1, entry))).decode()))
        db.execute('INSERT INTO ItemTable VALUES(?,?)', ('google-sign-in-token', SECRET))
    return Path(path)
