"""Cache public downloaded inputs only; every restored byte is rehashed.

No native object, archive, kernel, runtime seed or private identity is cached.
The author downloaders still run their original provenance/content checks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import tomllib

DEVICE = Path(__file__).resolve().parents[2]
BUILD = '24A446'
PREFIXES = ('out/ipsw/24A446/', 'device/.cache/firmware/')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(device=DEVICE):
    board = tomllib.loads((device / 'board.toml').read_text())
    contract = json.loads((device / 'scripts/clean-prelink-contract.json').read_text())
    spec = dict(framework='97437dcf7389484a0eeaa8067725ce743aff18ef', build=BUILD,
                firmware=board['firmware']['image'], proprietary=digest(device / 'proprietary-files.txt'),
                kernelcache=contract['inputs']['kernelcache'], implementation=digest(Path(__file__)))
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def safe(base, relative):
    if not any(relative.startswith(p) for p in PREFIXES) or '..' in Path(relative).parts or '\\' in relative:
        raise ValueError('Cache member outside public input directories')
    path = base / relative
    if not path.resolve().is_relative_to(base.resolve()) or path.is_symlink():
        raise ValueError('Cache path escapes its root')
    return path


def link_or_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if os.path.samefile(source, target):
            return
        raise ValueError('Refusing to replace an existing input: ' + str(target))
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def restore(cache, attempt, evidence):
    receipt = cache / 'manifest.json'
    if not receipt.is_file():
        (evidence / 'download-cache-restore.json').write_text(json.dumps(dict(hit=False)) + '\n')
        return
    record = json.loads(receipt.read_text())
    if record['identity'] != identity(attempt / 'device'):
        raise ValueError('Public download cache identity changed')
    checked = []
    # Verify the entire cache before placing any files in the new attempt.
    for row in record['files']:
        source = safe(cache / 'data', row['path'])
        if not source.is_file() or source.stat().st_size != row['bytes'] or digest(source) != row['sha256']:
            raise ValueError('Public download cache corruption: ' + row['path'])
        checked.append((source, safe(attempt, row['path'])))
    for source, target in checked:
        link_or_copy(source, target)
    (evidence / 'download-cache-restore.json').write_text(json.dumps(dict(
        hit=True, identity=record['identity'], files=len(checked), bytes=sum(r['bytes'] for r in record['files']),
        every_file_rehashed=True, build_objects_restored=False), indent=2) + '\n')
    print('Verified public download cache:', len(checked), 'files', flush=True)


def capture(cache, attempt, evidence):
    device = attempt / 'device'
    ipsw = attempt / 'out/ipsw' / BUILD
    firmware = device / '.cache/firmware'
    if not ipsw.is_dir() or not (firmware / 'sheng/porting-inputs.json').is_file():
        return False
    sys.path.insert(0, str(device / 'scripts'))
    from firmware_cache import verified_retained
    board = tomllib.loads((device / 'board.toml').read_text())
    if not verified_retained(firmware / 'sheng', board['firmware']['image']):
        return False
    expected = json.loads((device / 'scripts/clean-prelink-contract.json').read_text())['inputs']['kernelcache']
    if not (ipsw / 'kernelcache.decompressed').is_file():
        return False
    if digest(ipsw / 'kernelcache.decompressed') != expected:
        raise ValueError('Cached kernelcache differs from qualified pin')
    plains = list(ipsw.glob('*.dmg'))
    if not plains:
        return False  # Do not seal a permanent partial hit before runtime downloads.
    for plain in plains:
        record = json.loads(plain.with_suffix('.dmg.json').read_text())
        origin = json.loads(plain.with_suffix('.dmg.aea.json').read_text())
        if (record['size'] != plain.stat().st_size or record['sha256'] != digest(plain)
                or record['aea_sha256'] != origin['sha256'] or record['member'] != origin['member']):
            raise ValueError('Decrypted IPSW provenance/content changed')
    rows = []
    for directory in (ipsw, firmware):
        for source in sorted(directory.rglob('*')):
            if source.is_symlink():
                raise ValueError('Public cache contains an unexpected link')
            if not source.is_file() or source.name.endswith(('.partial', '.part', '.tgz', '.aea')):
                continue
            relative = source.relative_to(attempt).as_posix()
            safe(attempt, relative)
            row = dict(path=relative, bytes=source.stat().st_size, sha256=digest(source))
            target = safe(cache / 'data', relative)
            if target.exists() and not os.path.samefile(source, target):
                if digest(target) != row['sha256']:
                    raise ValueError('Public cache changed during capture')
            else:
                link_or_copy(source, target)
            rows.append(row)
    record = dict(identity=identity(device), files=rows, public_downloads_only=True,
                  compiled_objects=False, private_inputs=False)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    (evidence / 'download-cache-capture.json').write_text(json.dumps(dict(
        identity=record['identity'], files=len(rows), bytes=sum(r['bytes'] for r in rows)), indent=2) + '\n')
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a') as stream:
            stream.write('PUBLIC_DOWNLOAD_CACHE_READY=1\n')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['key'])
    parser.parse_args()
    print('key=sheng-public-downloads-v1-' + identity()[:24])
