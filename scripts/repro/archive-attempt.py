"""Preserve build/errors with fast gzip; omit only a proven duplicate ciphertext."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def duplicate_ciphertexts(root):
    omitted = []
    for plain in (root / 'out/ipsw/24A446').glob('*.dmg'):
        encrypted = plain.with_suffix('.dmg.aea')
        receipt, origin = plain.with_suffix('.dmg.json'), plain.with_suffix('.dmg.aea.json')
        if not all(p.is_file() for p in (encrypted, receipt, origin)):
            continue
        r, o = json.loads(receipt.read_text()), json.loads(origin.read_text())
        if (r.get('size') == plain.stat().st_size and r.get('member') == o.get('member') and
                r.get('sha256') == digest(plain) and r.get('aea_sha256') == o.get('sha256') == digest(encrypted)):
            omitted.append(dict(path=encrypted.relative_to(root).as_posix(), bytes=encrypted.stat().st_size,
                                sha256=o['sha256'], retained_plain=plain.relative_to(root).as_posix(),
                                plain_sha256=r['sha256']))
    return omitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.attempt.resolve()
    omitted = duplicate_ciphertexts(root)
    (root / 'evidence/archive-policy.json').write_text(json.dumps(dict(
        compression='gzip -1', omitted_git_metadata=True, omitted_duplicate_ciphertexts=omitted,
        source_logs_objects_and_diagnostics_retained=True), indent=2) + '\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = ['tar', '--exclude=.git', *('--exclude=./' + r['path'] for r in omitted), '-cf', '-', '-C', str(root), '.']
    with args.output.open('xb') as output:
        archive = subprocess.Popen(command, stdout=subprocess.PIPE)
        compressor = subprocess.Popen(['gzip', '-1'], stdin=archive.stdout, stdout=output)
        archive.stdout.close()
        zipped, packed = compressor.wait(), archive.wait()
        if zipped or packed:
            raise RuntimeError('Build archive/compression failed: ' + str((packed, zipped)))
    args.output.with_name('SHA256SUMS.txt').write_text(digest(args.output) + '  ' + args.output.name + '\n')


if __name__ == '__main__':
    main()
