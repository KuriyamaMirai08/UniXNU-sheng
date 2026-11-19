"""Offline regressions for the Stage 0C-1B dispatch and evidence fixes.

These tests exercise the real compile-evidence collector and, when supplied,
the pinned public-header fetcher. Fixture objects only test evidence handling;
they never qualify as ARM64 production compilation.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
production = load('stage0c1b_compile', HERE / 'run-stage0c1b.py')
PINNED_FETCHER = None


class CompileEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tree = self.root / 'tree'
        self.storage = self.tree / 'build/sheng-source-storage'
        self.storage.mkdir(parents=True)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()

    def test_failed_build_retains_completed_object_and_next_compiler_error(self):
        source = self.root / 'NativeUfs.cpp'
        source.write_bytes(b'fixture source\n')
        output = self.storage / 'NativeUfs.late.o'
        output.write_bytes(b'fixture object: evidence collection only')
        (self.storage / 'NativeUfs.log').write_text('compile finished\n')
        command = ['/pinned/apple/clang', '--target=arm64e-apple-ios27.0.0', '-Werror']
        (self.storage / 'NativeUfs.command.json').write_text(json.dumps(command))
        (self.storage / 'NativeRamBlock.log').write_text('error: fixture compiler failure\n')
        states = [dict(stage='kernel', status='failed', returncode=1)]
        result = production.finalize_evidence(self.tree, self.evidence,
                                             {'NativeUfs.cpp': source}, states)
        self.assertFalse(result['kernel_stage_passed'])
        self.assertEqual(result['stages'][0]['returncode'], 1)
        ufs = result['targets']['NativeUfs.cpp']
        self.assertEqual(ufs['object_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(ufs['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(ufs['command'], command)
        ram = result['targets']['NativeRamBlock.cpp']
        self.assertEqual(ram['errors'], 1)
        self.assertNotIn('object', ram)
        self.assertNotIn('object', result['targets']['BootLog.c'])
        self.assertEqual((self.evidence / 'compile-NativeRamBlock.log').read_text(),
                         'error: fixture compiler failure\n')
        self.assertEqual(json.loads((self.evidence / 'stage0c1b-result.json').read_text()), result)

    def test_failure_before_compilation_does_not_claim_objects_exist(self):
        result = production.finalize_evidence(
            self.root / 'absent-tree', self.evidence, {},
            [dict(stage='dependencies', status='failed', returncode=1)])
        self.assertFalse(result['kernel_stage_passed'])
        for target in result['targets'].values():
            self.assertNotIn('object', target)

    def test_successful_kernel_stage_is_recorded_separately_from_objects(self):
        result = production.finalize_evidence(
            self.tree, self.evidence, {}, [dict(stage='kernel', status='passed', returncode=0)])
        self.assertTrue(result['kernel_stage_passed'])
        for target in result['targets'].values():
            self.assertNotIn('object', target)

    def test_invalid_command_evidence_is_not_silently_accepted(self):
        (self.storage / 'NativeUfs.command.json').write_text('not valid JSON')
        with self.assertRaises(json.JSONDecodeError):
            production.finalize_evidence(self.tree, self.evidence, {}, [])

    def run_early_failure(self, collector_error=None):
        env_file = self.root / 'github-env'
        variables = {'RUNNER_TEMP': str(self.root), 'GITHUB_RUN_ID': 'fixture-run',
                     'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ENV': str(env_file)}
        with patch.dict(os.environ, variables), patch.object(production.subprocess, 'Popen') as spawn:
            spawn.return_value.wait.return_value = 1
            if collector_error:
                with patch.object(production, 'collect_object_evidence', side_effect=collector_error):
                    with self.assertRaisesRegex(RuntimeError, 'First failed stage: environment'):
                        production.main()
            else:
                with self.assertRaisesRegex(RuntimeError, 'First failed stage: environment'):
                    production.main()
        return self.root / 'stage0c1b/fixture-run-1/current/evidence'

    def test_main_finally_collects_evidence_after_early_failure(self):
        evidence = self.run_early_failure()
        result = json.loads((evidence / 'stage0c1b-result.json').read_text())
        self.assertFalse(result['kernel_stage_passed'])
        self.assertEqual(result['stages'][0]['returncode'], 1)
        self.assertEqual(json.loads((evidence / 'stage0c1b-summary.json').read_text())['stages'],
                         [['environment', 'failed', 1]])

    def test_main_preserves_original_failure_when_collector_also_fails(self):
        evidence = self.run_early_failure(ValueError('fixture invalid object metadata'))
        self.assertEqual((evidence / 'evidence-collection-error.txt').read_text(),
                         'fixture invalid object metadata\n')
        self.assertTrue((evidence / 'stage0c1b-summary.json').is_file())


class WorkflowTests(unittest.TestCase):
    def test_public_header_fetch_has_contents_read_job_token(self):
        workflow = (HERE.parents[1] / '.github/workflows/sheng-stage0c1b-compile.yml').read_text()
        self.assertIn('permissions:\n  contents: read\n', workflow)
        compile_step = workflow.split('      - name: Compile the patched production sources\n', 1)[1]
        compile_step = compile_step.split('      - name:', 1)[0]
        self.assertIn('          GITHUB_TOKEN: ${{ github.token }}\n', compile_step)
        self.assertIn('runs-on: macos-26', workflow)


class PinnedHeaderFetcherTests(unittest.TestCase):
    def setUp(self):
        if PINNED_FETCHER is None:
            self.skipTest('Pass --pinned-fetcher to exercise the archived production fetcher')
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'fixture-read-only-token', 'GH_TOKEN': ''}):
            self.fetcher = load('pinned_header_fetcher', PINNED_FETCHER)

    def request_to(self, url):
        requests = []

        def open_request(request, timeout):
            requests.append(request)
            self.assertEqual(timeout, 30)
            return io.BytesIO(b'fixture public header')

        with patch.object(self.fetcher.urllib.request, 'urlopen', side_effect=open_request):
            self.assertEqual(self.fetcher.fetch(url), b'fixture public header')
        return requests[0]

    def test_existing_fetcher_authenticates_github_api(self):
        request = self.request_to('https://api.github.com/repos/apple-oss-distributions/xnu/contents/iokit/DriverKit')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-read-only-token')

    def test_existing_fetcher_authenticates_raw_github(self):
        request = self.request_to('https://raw.githubusercontent.com/apple-oss-distributions/xnu/pinned/public.h')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-read-only-token')

    def test_token_is_not_sent_to_other_host_or_hostname_suffix(self):
        for url in ['https://example.invalid/public.h', 'https://api.github.com.example.invalid/public.h']:
            with self.subTest(url=url):
                request = self.request_to(url)
                self.assertIsNone(request.get_header('Authorization'))

    def test_anonymous_request_has_no_authorization_header(self):
        self.fetcher.TOKEN = None
        request = self.request_to('https://api.github.com/repos/apple-oss-distributions/xnu/contents/iokit/DriverKit')
        self.assertIsNone(request.get_header('Authorization'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pinned-fetcher', type=Path)
    options, remainder = parser.parse_known_args()
    PINNED_FETCHER = options.pinned_fetcher
    unittest.main(argv=[sys.argv[0], *remainder])
