"""Regression for the non-default output layout used by clean hosted builds."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run


class SourcePaths(unittest.TestCase):
    def test_child_receives_checkout_paths_with_sibling_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root/'device'
            framework = root/'UniXNU'
            evidence = root/'evidence'
            tree = root/'out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree'
            for path in (device, framework/'scripts', evidence, tree):
                path.mkdir(parents=True)
            helper = framework/'scripts/build-sheng-source-drivers.py'
            helper.write_text('# fixture helper\n')
            digest = run.hashlib.sha256(helper.read_bytes()).hexdigest()
            with patch.dict(os.environ, {'UNIXNU_ROOT': 'old', 'UNIXNU_DEVICE': 'old'}), \
                    patch.object(run, 'DRIVER_HELPER_SHA256', digest):
                record = run.configure_source_paths(device, framework, evidence)
                child = subprocess.check_output([
                    sys.executable, '-c',
                    'import json,os; print(json.dumps({k:os.environ[k] for k in '
                    '("UNIXNU_ROOT","UNIXNU_DEVICE")}))'], cwd=tree, text=True)
                self.assertEqual(json.loads(child), {
                    'UNIXNU_ROOT': str(framework.resolve()),
                    'UNIXNU_DEVICE': str(device.resolve())})
                self.assertEqual(tree.parents[4], root)
                self.assertEqual(json.loads((evidence/'source-paths.json').read_text()), record)
                self.assertEqual(Path(record['helper']), helper.resolve())

    def test_missing_or_modified_helper_is_rejected_before_environment_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (root/'device', root/'UniXNU/scripts', root/'evidence'):
                path.mkdir(parents=True)
            with patch.dict(os.environ, {'UNIXNU_ROOT': 'original'}):
                with self.assertRaisesRegex(RuntimeError, 'Missing or external'):
                    run.configure_source_paths(root/'device', root/'UniXNU', root/'evidence')
                (root/'UniXNU/scripts/build-sheng-source-drivers.py').write_text('# unknown\n')
                with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                    run.configure_source_paths(root/'device', root/'UniXNU', root/'evidence')
                self.assertEqual(os.environ['UNIXNU_ROOT'], 'original')
                self.assertFalse((root/'evidence/source-paths.json').exists())

    def test_external_helper_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (root/'device', root/'UniXNU/scripts', root/'evidence'):
                path.mkdir(parents=True)
            outside = root/'outside.py'
            outside.write_text('# external\n')
            helper = root/'UniXNU/scripts/build-sheng-source-drivers.py'
            try:
                helper.symlink_to(outside)
            except OSError as error:
                self.skipTest('Symlinks unavailable: '+str(error))
            with self.assertRaisesRegex(RuntimeError, 'Missing or external'):
                run.configure_source_paths(root/'device', root/'UniXNU', root/'evidence')


if __name__ == '__main__':
    unittest.main()
