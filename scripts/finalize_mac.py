"""Keep bundled OpenSSL consistent with the Python runtime used by py2app."""
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    contents = Path(sys.argv[1]).resolve() / 'Contents'
    frameworks = contents / 'Frameworks'
    names = {'libcrypto.3.dylib', 'libssl.3.dylib'}
    # The runner also has Homebrew OpenSSL. py2app flattens both distributions
    # into Frameworks, allowing incompatible same-named libraries to overwrite
    # each other. Use the pair shipped with our Python framework consistently.
    for name in sorted(names):
        original = Path(sys.base_prefix) / 'lib' / name
        if not original.is_file():
            raise RuntimeError(f'Python OpenSSL library missing: {original}')
        target = frameworks / name
        shutil.copy2(original, target)
        subprocess.run(['install_name_tool', '-id', f'@executable_path/../Frameworks/{name}', str(target)], check=True)

    macho = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
             b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}
    for binary in contents.rglob('*'):
        if binary.is_symlink() or not binary.is_file():
            continue
        with binary.open('rb') as stream:
            if stream.read(4) not in macho:
                continue
        dependencies = subprocess.check_output(['otool', '-L', str(binary)], text=True)
        for line in dependencies.splitlines()[1:]:
            old = line.strip().split(' (', 1)[0]
            name = Path(old).name
            if name in names:
                new = f'@executable_path/../Frameworks/{name}'
                if old != new:
                    subprocess.run(['install_name_tool', '-change', old, new, str(binary)], check=True)
    print('Bundled the matching Python OpenSSL library pair')


if __name__ == '__main__':
    main()
