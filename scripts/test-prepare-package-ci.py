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


if __name__ == '__main__':
    unittest.main()
