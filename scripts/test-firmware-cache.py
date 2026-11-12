import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from firmware_cache import required_free_bytes, verified_retained


class FirmwareCache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = {'url': 'https://example.invalid/firmware.tgz', 'sha256': 'a' * 64, 'bytes': 1000}
        (self.root / 'porting-inputs').mkdir()
        (self.root / 'porting-inputs/uefi.elf').write_bytes(b'public fixture')
        self.record = dict(source_url=self.image['url'], archive_sha256=self.image['sha256'],
                           archive_bytes=1000, archive_deleted=True, gzip_integrity_verified=True,
                           selected=[dict(file='uefi.elf', bytes=14, sha256=hashlib.sha256(b'public fixture').hexdigest())])
        self.save()

    def save(self):
        (self.root / 'porting-inputs.json').write_text(json.dumps(self.record))

    def test_valid_retained_and_missing_record(self):
        self.assertTrue(verified_retained(self.root, self.image))
        (self.root / 'porting-inputs.json').unlink()
        self.assertFalse(verified_retained(self.root, self.image))

    def test_same_size_corruption_is_rejected(self):
        (self.root / 'porting-inputs/uefi.elf').write_bytes(b'corruptfixture')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            verified_retained(self.root, self.image)

    def test_wrong_provenance_and_escaping_paths_are_rejected(self):
        self.record['archive_sha256'] = 'b' * 64
        self.save()
        with self.assertRaises(ValueError):
            verified_retained(self.root, self.image)
        self.record['archive_sha256'] = self.image['sha256']
        self.record['selected'][0]['file'] = '../uefi.elf'
        self.save()
        with self.assertRaises(ValueError):
            verified_retained(self.root, self.image)

    def test_download_space_accounts_for_existing_allocation(self):
        self.assertEqual(required_free_bytes(1000, 400), 600 + (2 << 30) + (512 << 20))


if __name__ == '__main__':
    unittest.main()
