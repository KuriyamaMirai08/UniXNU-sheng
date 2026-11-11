#!/usr/bin/env python3
"""Execute the formal prelink engine on retained real inputs, with strict binding and persistent failures."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--unixnu', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--logs', type=Path, required=True)
args = p.parse_args()
device = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(args.unixnu / 'scripts'))
from unixnu import cli, kernel, ipsw
from unixnu.config import Context

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

ctx = Context(cli.parser().parse_args(['build', 'prelink', '-D', str(device), '--os', '27', '--out', str(args.out)]))
ctx.logs = args.logs / 'pipeline'
ctx.logs.mkdir(parents=True, exist_ok=True)
cli.prepare(ctx, ['kernel'])  # Source links only; never invokes kernel.build.
spec = ctx.board['kernel']['prelink']
native = ctx.tree / spec['kernel']
native_sha = sha(native)
if native_sha != '31f8273297025436fa9814b9540329b439af45afd661f7f6836476401a9ec15b':
    raise SystemExit('Native input differs from the successful M4 link checkpoint; review/rebuild inputs explicitly')
reference = ctx.tree / 'build/xnu/fileset-reference/mach.release.bcm2837.unstripped.noctf'
reference_sha = sha(reference)
if json.loads(reference.with_suffix('.json').read_text())['sha256'] != reference_sha:
    raise SystemExit('Retained RELEASE reference digest does not match its build receipt')
# The historical profile permits incomplete experimental images. This stage
# requires complete bindings and disables its panic-stub fallback, preserving
# the full root list, ABI checks and regression policy.
spec['extra_args'] = [a for a in spec.get('extra_args', []) if a != '--allow-missing']
cache = args.out / 'ipsw' / ctx.board['ipsw']['build'] / 'kernelcache.decompressed'
if not cache.is_file() or sha(cache) != spec['kernelcache_sha256']:
    cache = ipsw.kernelcache(ctx, ipsw.Ipsw(ctx))  # HTTP ranges; KernelCache only.
ctx.args.kernelcache = str(cache)
sys.path.insert(0, str(ctx.tree / 'kits/XnuPrelink'))
from kc_image import Image
from fileset_emit import dependency_closure, rebase_collection
from fileset_layout import Layout

inputs = {'native': str(native), 'native_sha256': native_sha,
          'reference': str(reference), 'reference_sha256': reference_sha,
          'kernelcache': str(cache), 'kernelcache_sha256': sha(cache),
          'roots': spec['roots'], 'allow_missing': False, 'build_invoked': False}
(args.logs / 'prelink-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
print('Real retained prelink inputs:', json.dumps(inputs), flush=True)

# Use the same actual collection rebase/layout as the emitter to record DATA
# capacity. This evidence cannot turn a failed real prelink into success.
raw, native_data = cache.read_bytes(), native.read_bytes()
stock, executable = Image(raw), Image(native_data)
closure = dependency_closure(stock, spec['roots'])
initializers = dict([spec['early_security_init'].split('=', 1)]) if spec.get('early_security_init') else {}
initializers = {name: int(address, 0) for name, address in initializers.items()}
rebased, slide, _ = rebase_collection(stock, executable.base, closure, initializers, set(spec['roots']))
layout_report = {'native_data_bytes': next(s['size'] for s in executable.segments if s['name'] == '__DATA'),
                 'closure_entries': len(closure), 'collection_slide': hex(slide)}
try:
    layout = Layout(rebased, executable, closure)
    layout_report.update(layout_valid=True, placements=layout.describe())
except ValueError as error:
    layout_report.update(layout_valid=False, error=str(error))
(args.logs / 'data-layout.json').write_text(json.dumps(layout_report, indent=2) + '\n')
print('Actual-input DATA layout:', json.dumps(layout_report), flush=True)

class RetainedAttempt:
    def __init__(self, **kwargs):
        self.path = tempfile.mkdtemp(**kwargs)
    def __enter__(self):
        print('Retaining prelink attempt directory:', self.path, flush=True)
        return self.path
    def __exit__(self, *exception):
        return False

# Change only temporary-directory lifetime. The formal emitter, candidate
# validation, regression checks and atomic publication stay unchanged.
kernel.tempfile = SimpleNamespace(TemporaryDirectory=RetainedAttempt)
try:
    result = kernel.prelink(ctx)
finally:
    for filename in ('kernel.json', 'kernel.failed.json', 'kernel.map.json'):
        path = ctx.work / 'kernel' / filename
        if path.is_file():
            shutil.copy2(path, args.logs / filename)
    if sha(native) != native_sha or sha(reference) != reference_sha:
        raise RuntimeError('Prelink modified a retained native/reference input')

record = json.loads(result.with_suffix('.json').read_text())
if record.get('missing') or record.get('stubbed') or not record.get('mapping_complete'):
    raise RuntimeError('Prelink bindings are incomplete or use fallback stubs')
if record.get('statistics', {}).get('unproven_kernel_page_references', 0):
    raise RuntimeError('Prelink retains unproven kernel page references; ABI validation is incomplete')
image = Image(result.read_bytes())
if image.kind != 12 or 'com.apple.kernel' not in image.entries:
    raise RuntimeError('Expected a complete MH_FILESET with the native kernel entry')
root_fixups = image.fixups()  # Real chain parser checks bounds/pointer formats.
for name, (_, offset) in image.entries.items():
    member = Image(image.data, offset)
    for segment in member.segments:
        if segment['fileoff'] + segment['filesize'] > len(image.data):
            raise RuntimeError(f'{name}: segment exceeds file bounds')
        if segment['size'] and segment['name'] != '__LINKEDIT' and not any(
                root['va'] <= segment['va'] and segment['va'] + segment['size'] <= root['va'] + root['size']
                for root in image.segments):
            raise RuntimeError(f'{name}: segment outside root mappings')
    for section in member.sections:
        if section['size'] and not any(s['name'] == section['segment'] and s['va'] <= section['va']
                and section['va'] + section['size'] <= s['va'] + s['size'] for s in member.segments):
            raise RuntimeError(f'{name}: section outside its segment')
native_member = Image(image.data, image.entries['com.apple.kernel'][1])
if struct.unpack_from('<I', image.data, native_member.at + 8)[0] & 0xff != 2:
    raise RuntimeError('Native fileset member is not arm64e')
report = {'output': str(result), 'sha256': sha(result), 'bytes': result.stat().st_size,
          'format': 'MH_FILESET', 'entries': len(image.entries), 'root_fixups': len(root_fixups),
          'mapping_complete': True, 'regression_policy': 'pass', 'layout': layout_report,
          'statistics': record.get('statistics'), 'runtime_qualified': False, 'installation_images': False}
(args.logs / 'prelink-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS: strict real prelink and structural validation', json.dumps(report, indent=2), flush=True)
