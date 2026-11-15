#!/usr/bin/env python3
"""Check that retained-input recovery cannot publish weakened or stale evidence.

Pass the original kit/policy/regression source and current cache/native to
exercise the same production object/consumer guard on real retained bytes.
"""
import argparse
import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import clean_prelink_recovery as recovery


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(recovery.CONTRACT.read_text(encoding='utf-8'))
        recovery.check_kit(OPTIONS.kit, cls.contract)
        sys.path.insert(0, str(OPTIONS.kit))
        from kc_image import Image
        from fileset_emit import dependency_closure
        cls.raw = recovery.read_pinned(OPTIONS.kernelcache, cls.contract['inputs']['kernelcache'], 'Kernelcache')
        cls.native = recovery.read_pinned(OPTIONS.native, cls.contract['inputs']['native'], 'Native')
        cls.document = json.loads(recovery.read_pinned(
            recovery.FIXTURE, cls.contract['reviewed_fixture_sha256'], 'Fixture'))
        cls.policy = json.loads(recovery.read_pinned(
            OPTIONS.policy, cls.contract['regression_policy_sha256'], 'Policy'))
        cls.regression = recovery.read_pinned(
            OPTIONS.regression_source, cls.contract['regression_source_sha256'], 'Regression source')
        cls.closure = dependency_closure(Image(cls.raw), cls.contract['roots'])

    def guard(self, document=None, native=None, raw=None, closure=None):
        from m4_prelink_evidence import validate
        return validate(document or self.document, raw or self.raw, native or self.native,
                        closure or self.closure)

    def test_original_contracts_pass(self):
        result = self.guard()
        self.assertEqual(result['reviewed_functions'], 13)
        self.assertEqual(result['processor_info']['qualified_flavors'], [1])
        self.assertFalse(result['processor_info']['flavor_3_qualified'])
        self.assertEqual(result['image4_storage']['bytes'], 0x1400)

    def test_changed_input_digest_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'unknown-native'
            path.write_bytes(b'unknown native')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                recovery.read_pinned(path, self.contract['inputs']['native'], 'Native')

    def test_changed_function_bytes_rejected(self):
        from kc_image import Image
        native = Image(self.native)
        address = next(a for a, names in native.symbols().items() if '_vm_map_page_size' in names)
        altered = bytearray(self.native)
        altered[native.offset(address)] ^= 1
        with self.assertRaisesRegex(ValueError, 'Reviewed native implementation changed'):
            self.guard(native=bytes(altered))

    def test_zero_assertion_flag_rejected(self):
        from kc_image import Image
        native = Image(self.native)
        address = next(a for a, names in native.symbols().items() if '_kext_assertions_enable' in names)
        altered = bytearray(self.native)
        struct.pack_into('<I', altered, native.offset(address), 0)
        with self.assertRaisesRegex(ValueError, 'Reviewed native object content changed'):
            self.guard(native=bytes(altered))

    def test_panic_authentication_change_rejected(self):
        altered = copy.deepcopy(self.document)
        hook = next(row for row in altered['data'] if row['native_symbol'] == '_PE_arm_debug_panic_hook')
        hook['native_fixup']['fields'][2] ^= 1
        with self.assertRaisesRegex(ValueError, 'Reviewed native hook target/authentication changed'):
            self.guard(document=altered)

    def test_changed_processor_consumer_rejected(self):
        altered = copy.deepcopy(self.document)
        altered['processor_info_contract']['caller_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'processor_info caller bytes changed'):
            self.guard(document=altered)

    def test_changed_closure_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Closure changed'):
            self.guard(closure=set(self.closure) | {'unreviewed.consumer'})

    def test_extra_reviewed_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            kit = Path(folder)
            (kit / 'fixtures').mkdir()
            contract = dict(engine={}, engine_fixtures={})
            (kit / 'fixtures/fileset-unreviewed-symbols.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'fixture inventory changed'):
                recovery.check_kit(kit, contract)

    def test_incomplete_publication_refused_with_original_report(self):
        from fileset_emit import write_candidate
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'kernel.macho'
            report_path = Path(folder) / 'kernel.json'
            report = dict(missing={'consumer': {'0x1': 1}}, stubbed={}, statistics={},
                          mapping_complete=False, loadable=False, runtime_qualified=False)
            with self.assertRaisesRegex(ValueError, 'Incomplete pairing'):
                recovery.publish(b'fixture only', report, output, report_path, self.regression, self.policy)
            self.assertFalse(output.exists())
            saved = json.loads(report_path.read_text())
            self.assertFalse(saved['candidate_written'])
            self.assertEqual(saved['missing'], report['missing'])
            self.assertFalse(saved['loadable'])
            self.assertFalse(saved['runtime_qualified'])

    def test_stub_publication_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'kernel.macho'
            report_path = Path(folder) / 'kernel.json'
            report = dict(missing={}, stubbed={'consumer': {'0x1': 1}}, statistics={})
            with self.assertRaisesRegex(ValueError, 'stubbed or unproven-page'):
                recovery.publish(b'fixture only', report, output, report_path, self.regression, self.policy)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(report_path.read_text())['candidate_written'])

    def test_original_required_branches_check_retained(self):
        record = dict(collection_slide='0x0', missing={}, stubbed={}, native_original_branches=[])
        with self.assertRaisesRegex(ValueError, 'required absolute adapter'):
            recovery.run_original_regression_check(self.regression, record, self.policy)

    def test_original_new_gap_check_retained(self):
        record = dict(collection_slide='0x0', missing={'unreviewed': {'0x1': 1}}, stubbed={})
        with self.assertRaisesRegex(ValueError, 'prelink regression'):
            recovery.run_original_regression_check(self.regression, record, self.policy)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('kit', 'kernelcache', 'native', 'policy', 'regression-source'):
        parser.add_argument('--' + option, required=True, type=Path)
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
