import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('prepare_ci', Path(__file__).with_name('prepare-package-ci.py'))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class FetchPreparation(unittest.TestCase):
    def test_exact_fetch_and_noncone_paths(self):
        source = 'def fetch(source, directory):\n' + ci.OLD + '\n        subprocess.run(["sparse-checkout", "add"])\n'
        result = ci.transform(source)
        self.assertIn('source["commit"]', result)
        self.assertNotIn('"clone"', result)
        self.assertNotIn('"sparse-checkout", "add"', result)
        self.assertIn('kernel.googlesource.com', result)

    def test_drift_and_ambiguous_matches_stop(self):
        for source in ('changed source', ci.OLD + ci.OLD):
            with self.assertRaises(ValueError):
                ci.transform(source)


    def test_cached_compilation_record_without_generated_headers_bootstraps(self):
        # This represents the pinned builder: entry and error-handler conditions.
        source = (
            'def build(ctx):\\n'
            "    record = ctx.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'\\n"
            '    if not record.is_file():\\n'
            '        pass\\n'
            '    try:\\n'
            '        pass\\n'
            '    except Exception:\\n'
            '        if not record.is_file():\\n'
            '            raise\\n'
        )
        updated = ci.transform_kernel_bootstrap(source)
        self.assertIn('if not record.is_file() or missing_headers:', updated)
        self.assertIn('kern/clock.h', updated)
        self.assertIn('pexpert/pexpert.h', updated)
        self.assertEqual(updated.count('if not record.is_file():'), 1)
        with self.assertRaises(ValueError):
            ci.transform_kernel_bootstrap(source.replace('startup.o.json', 'other.o.json'))


if __name__ == '__main__':
    unittest.main()
