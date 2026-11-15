#!/usr/bin/env python3
"""Check the real reference builder's two-link publication transaction.

These isolated control-flow fixtures supply subprocess responses only. No
fixture object, archive or executable enters a production native/reference
build. Actual compiler/linker checks remain separate, required build stages.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REFERENCE = None


class ReferencePublicationTests(unittest.TestCase):
    def exercise(self, final_exit):
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
            links = []

            def subprocess_response(command, **kwargs):
                if command[:2] == ["xcrun", "nm"]:
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
                if final_exit:
                    kwargs["stdout"].write('  "_missing_real_provider", referenced from:\n      consumer.o\n')
                else:
                    (objects / "mach.release.bcm2837.unstripped").write_bytes(b"fixture-success-marker")
                return SimpleNamespace(returncode=final_exit)

            with patch.object(REFERENCE.subprocess, "run", side_effect=subprocess_response), \
                    patch.object(REFERENCE.subprocess, "check_output", return_value="fixture compiler"), \
                    patch("sys.argv", ["reference", "--tree", str(root), "--lto"]):
                if final_exit:
                    with self.assertRaises(SystemExit) as refused:
                        REFERENCE.main()
                    self.assertEqual(refused.exception.code, final_exit)
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
            self.assertEqual(final.is_file(), not final_exit)
            self.assertEqual(record.is_file(), not final_exit)
            if not final_exit:
                self.assertEqual(final.read_bytes(), b"fixture-success-marker")

    def test_unavailable_forced_export_reconciles_before_successful_publication(self):
        self.exercise(0)

    def test_missing_real_provider_at_final_link_refuses_publication(self):
        self.exercise(1)


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
