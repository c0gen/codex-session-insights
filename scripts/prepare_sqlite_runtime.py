"""Prepare a fixed SQLite DLL without changing the machine's Python install.

Pass a Windows x64 sqlite3.dll from a trusted runtime or sqlite.org distribution.
The build records its SHA256 and verifies the library loaded by the final EXE.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('library', type=Path)
args = parser.parse_args()
source = args.library.resolve(strict=True)
dll = ctypes.WinDLL(str(source))
dll.sqlite3_libversion.restype = ctypes.c_char_p
dll.sqlite3_sourceid.restype = ctypes.c_char_p
version = dll.sqlite3_libversion().decode()
if tuple(map(int, version.split('.'))) < (3, 51, 3):
    raise SystemExit('SQLite 3.51.3 or later is required')
target = Path(__file__).resolve().parents[1] / '.local-data' / 'sqlite-runtime'
target.mkdir(parents=True, exist_ok=True)
if source != target / 'sqlite3.dll':
    shutil.copyfile(source, target / 'sqlite3.dll')
manifest = dict(version=version, source_id=dll.sqlite3_sourceid().decode(),
                sha256=hashlib.sha256(source.read_bytes()).hexdigest())
(target / 'runtime.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps(manifest))
