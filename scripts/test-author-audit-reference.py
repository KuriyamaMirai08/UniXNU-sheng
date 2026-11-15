#!/usr/bin/env python3
"""Check the real reference builder's two-link publication transaction.

These isolated control-flow fixtures supply subprocess responses only. No
fixture object, archive or executable enters a production native/reference
build. Actual compiler/linker checks remain separate, required build stages.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REFERENCE = None


class ReferencePublicationTests(unittest.TestCase):
    def exercise(self, final_exit, native_diagnostics=False, omit_diagnostic=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (".cache/xnu-work/osfmk/arm64/sleh.c",
                         ".cache/fakeroot/usr/include/header.h",
                         "build/corecrypto-2023/libcorecrypto_kernel_noasm-namespaced.a",
                         "build/libpthread-kernel/libpthread_kernel.a",
                         "build/armdt-platform/libArmDTPlatform.a",
                         "build/armcpu/libArmCpu.a"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"control-flow fixture; never a build input")
            config = root / ".cache/xnu-work/config"
            config.mkdir()
            (config / "Private.exports").write_text("_available\n_unavailable_export\n")
            (config / "Private.arm64.exports").write_text("")
            original_config = None
            if native_diagnostics:
                fixture = Path(__file__).parent / 'fixtures/reference-native-diagnostics/MASTER.arm64.bcm2837'
                original_config = fixture.read_bytes()
                (config / 'MASTER.arm64.bcm2837').write_bytes(original_config)
                for name in ('san/memory/ubsan_minimal.c', 'san/memory/ubsan_minimal.h', 'san/conf/files.arm64',
                             'osfmk/kern/debug.c', 'osfmk/kern/assert.h', 'osfmk/machine/static_if.h',
                             'osfmk/kern/startup.c', 'osfmk/arm64/sleh.c'):
                    path = root / '.cache/xnu-work' / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'control-flow fixture; actual implementation compiled in the clean build')
            links = []

            def subprocess_response(command, **kwargs):
                if command[:2] == ["xcrun", "nm"]:
                    if native_diagnostics and command[-1].endswith('mach.release.bcm2837.unstripped'):
                        names = set(REFERENCE.NATIVE_DIAGNOSTIC_SYMBOLS)
                        if omit_diagnostic:
                            names.remove('_mach_assert_jump_key')
                        return SimpleNamespace(returncode=0, stdout='\n'.join(sorted(names)) + '\n')
                    return SimpleNamespace(returncode=0, stdout="_available\n")
                self.assertEqual(command[0], "make")
                values = dict(arg.split("=", 1) for arg in command if "=" in arg)
                links.append(command[:])
                objects = Path(values["OBJROOT"]) / "RELEASE_ARM64_BCM2837"
                objects.mkdir(parents=True, exist_ok=True)
                (objects / "nonltolink.filelist").write_text("")
                (objects / "justlto.o").write_bytes(b"control-flow fixture")
                if len(links) == 1:
                    kwargs["stdout"].write('  "_unavailable_export", referenced from:\n      <initial-undefines>\n')
                    return SimpleNamespace(returncode=1)
                private = Path(command[2]) / "config/Private.exports"
                self.assertEqual(private.read_text(), "_available\n")
                self.assertEqual(values['KERNEL_CONFIGS'], 'RELEASE')
                self.assertEqual(values['BUILD_LTO'], '1')
                if native_diagnostics:
                    modified = (Path(command[2]) / 'config/MASTER.arm64.bcm2837').read_text()
                    self.assertIn('#  KERNEL_RELEASE = [ KERNEL_BASE release mach_assert ]', modified)
                    self.assertIn('#  VM_RELEASE =     [ VM_BASE ubsan_minimal ]', modified)
                if final_exit:
                    kwargs["stdout"].write('  "_missing_real_provider", referenced from:\n      consumer.o\n')
                else:
                    (objects / "mach.release.bcm2837.unstripped").write_bytes(b"fixture-success-marker")
                return SimpleNamespace(returncode=final_exit)

            arguments = ['reference', '--tree', str(root), '--lto']
            if native_diagnostics:
                arguments.append('--native-diagnostics')
            with patch.object(REFERENCE.subprocess, "run", side_effect=subprocess_response), \
                    patch.object(REFERENCE.subprocess, "check_output", return_value="fixture compiler"), \
                    patch("sys.argv", arguments):
                if final_exit:
                    with self.assertRaises(SystemExit) as refused:
                        REFERENCE.main()
                    self.assertEqual(refused.exception.code, final_exit)
                elif omit_diagnostic:
                    with self.assertRaisesRegex(ValueError, 'lacks genuine'):
                        REFERENCE.main()
                else:
                    REFERENCE.main()
            self.assertEqual(len(links), 2)
            build = root / "build/xnu/fileset-reference"
            first = list(build.glob("lto-*/first-link-undefineds.json"))
            self.assertEqual(len(first), 1)
            self.assertEqual(json.loads(first[0].read_text()), ["_unavailable_export"])
            removed = json.loads(first[0].with_name("omitted-unavailable-forced-exports.json").read_text())
            self.assertEqual(removed, ["_unavailable_export"])
            self.assertFalse(list(build.rglob("native-stubs.*")))
            final = build / "mach.release.bcm2837.unstripped.noctf"
            record = final.with_suffix(".json")
            self.assertEqual(final.is_file(), not (final_exit or omit_diagnostic))
            self.assertEqual(record.is_file(), not (final_exit or omit_diagnostic))
            if original_config is not None:
                self.assertEqual((config / 'MASTER.arm64.bcm2837').read_bytes(), original_config)
                self.assertEqual(hashlib.sha256(original_config).hexdigest(),
                                 'dba44ba3ab4d913afa315d8c213461f62ee15d894ac71ce1ccee58fd304301ff')
            if not (final_exit or omit_diagnostic):
                self.assertEqual(final.read_bytes(), b"fixture-success-marker")
                if native_diagnostics:
                    receipt = json.loads(record.read_text())
                    self.assertTrue(receipt['inputs']['native_diagnostics'])
                    self.assertEqual(receipt['native_archive_diagnostics']['final_defined_symbols_verified'],
                                     sorted(REFERENCE.NATIVE_DIAGNOSTIC_SYMBOLS))

    def test_unavailable_forced_export_reconciles_before_successful_publication(self):
        self.exercise(0)

    def test_missing_real_provider_at_final_link_refuses_publication(self):
        self.exercise(1)

    def test_native_archive_diagnostics_selects_real_private_configuration(self):
        self.exercise(0, native_diagnostics=True)

    def test_successful_link_without_all_diagnostics_refuses_publication(self):
        self.exercise(0, native_diagnostics=True, omit_diagnostic=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder", type=Path, required=True)
    options = parser.parse_args()
    global REFERENCE
    spec = importlib.util.spec_from_file_location("audited_reference", options.builder)
    REFERENCE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(REFERENCE)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReferencePublicationTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
