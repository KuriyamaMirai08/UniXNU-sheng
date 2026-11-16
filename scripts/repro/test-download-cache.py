"""Check cross-attempt reuse, input corruption refusal and archive deduplication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import download_cache as cache


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def jwrite(path, value):
    write(path, (json.dumps(value) + '\n').encode())


class PublicDownloads(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(cache.os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        cache.os.environ.pop('GITHUB_ENV', None)  # Fixtures must never publish runner readiness.

    def fixture(self, root):
        device = root / 'device'
        write(device / 'board.toml', b'[firmware.image]\nurl="https://example.invalid/public.tgz"\nsha256="archive"\nbytes=123\n')
        write(device / 'proprietary-files.txt', b'public fixture\n')
        shutil.copyfile(cache.DEVICE / 'scripts/firmware_cache.py', self.mkdir(device / 'scripts/firmware_cache.py'))
        kernel = root / 'out/ipsw/24A446/kernelcache.decompressed'
        write(kernel, b'public kernelcache fixture')
        jwrite(device / 'scripts/clean-prelink-contract.json', dict(inputs=dict(kernelcache=cache.digest(kernel))))
        firmware = device / '.cache/firmware/sheng'
        write(firmware / 'porting-inputs/uefi.elf', b'public vendor fixture')
        jwrite(firmware / 'porting-inputs.json', dict(archive_deleted=True, source_url='https://example.invalid/public.tgz',
            archive_sha256='archive', archive_bytes=123, gzip_integrity_verified=True,
            selected=[dict(file='uefi.elf', bytes=21, sha256=cache.digest(firmware / 'porting-inputs/uefi.elf'))]))
        plain = kernel.with_name('public.dmg')
        write(plain, b'public decrypted image fixture')
        encrypted = plain.with_suffix('.dmg.aea')
        write(encrypted, b'public encrypted image fixture')
        jwrite(plain.with_suffix('.dmg.json'), dict(size=plain.stat().st_size, sha256=cache.digest(plain),
            member='public.dmg.aea', aea_sha256=cache.digest(encrypted)))
        jwrite(plain.with_suffix('.dmg.aea.json'), dict(member='public.dmg.aea', sha256=cache.digest(encrypted)))
        evidence = root / 'evidence'
        evidence.mkdir()
        return evidence

    def mkdir(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def exercise(self, mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            attempt, saved, next_attempt = base / 'attempt', base / 'cache', base / 'next'
            evidence = self.fixture(attempt)
            self.assertTrue(cache.capture(saved, attempt, evidence))
            self.assertFalse(list((saved / 'data').rglob('*.aea')))
            next_attempt.mkdir()
            for relative in ('board.toml', 'proprietary-files.txt', 'scripts/clean-prelink-contract.json'):
                destination = self.mkdir(next_attempt / 'device' / relative)
                shutil.copyfile(attempt / 'device' / relative, destination)
            next_evidence = next_attempt / 'evidence'
            next_evidence.mkdir()
            if mutate:
                mutate(saved)
                with self.assertRaises(ValueError):
                    cache.restore(saved, next_attempt, next_evidence)
                self.assertFalse((next_attempt / 'out').exists())
            else:
                cache.restore(saved, next_attempt, next_evidence)
                self.assertEqual((next_attempt / 'out/ipsw/24A446/public.dmg').read_bytes(), b'public decrypted image fixture')
                self.assertTrue(json.loads((next_evidence / 'download-cache-restore.json').read_text())['every_file_rehashed'])

    def test_inputs_reused_and_ciphertext_not_duplicated(self):
        self.exercise()

    def test_changed_cached_bytes_refused_before_any_restore(self):
        def corrupt(saved):
            p = saved / 'data/out/ipsw/24A446/public.dmg'
            p.write_bytes(b'x' * p.stat().st_size)
        self.exercise(corrupt)

    def test_cache_path_traversal_refused(self):
        def corrupt(saved):
            path = saved / 'manifest.json'
            r = json.loads(path.read_text())
            r['files'][0]['path'] = 'out/ipsw/24A446/../../../../outside'
            path.write_text(json.dumps(r))
        self.exercise(corrupt)

    def test_changed_target_identity_refused(self):
        def corrupt(saved):
            path = saved / 'manifest.json'
            r = json.loads(path.read_text())
            r['identity'] = 'other target'
            path.write_text(json.dumps(r))
        self.exercise(corrupt)

    def test_only_verified_ciphertext_duplicate_is_omitted(self):
        spec = importlib.util.spec_from_file_location('archive_attempt', Path(__file__).with_name('archive-attempt.py'))
        archive = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(archive)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(len(archive.duplicate_ciphertexts(root)), 1)
            (root / 'out/ipsw/24A446/public.dmg').write_bytes(b'tampered')
            self.assertEqual(archive.duplicate_ciphertexts(root), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
