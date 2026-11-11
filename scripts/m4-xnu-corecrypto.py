#!/usr/bin/env python3
"""Real production-config XNU bootstrap and CoreCrypto, stopping before other archives/link/prelink/images."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--unixnu', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--logs', type=Path, required=True)
args = p.parse_args()
device = Path(__file__).resolve().parents[1]
args.logs.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('prepare_ci', device / 'scripts/prepare-package-ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
kernel_path = args.unixnu / 'scripts/unixnu/kernel.py'
original = subprocess.check_output(['git', '-C', args.unixnu, 'show', 'HEAD:scripts/unixnu/kernel.py'], text=True)
fixed = ci.transform_kernel_bootstrap(original)
# This stage must run make incrementally on EVERY retry, not merely accept an
# old startup record from a failed compile. No object/cache deletion is needed.
staged = fixed.replace('if not record.is_file() or missing_headers:',
                      "if not record.is_file() or missing_headers or env.get('UNIXNU_XNU_COMPILE_STAGE') == '1':")
if kernel_path.read_text() not in (original, fixed, staged):
    raise SystemExit('Unreviewed local kernel builder edits; retained for inspection')
if kernel_path.read_text() != staged:
    kernel_path.write_text(staged)
sys.path.insert(0, str(args.unixnu / 'scripts'))
from unixnu import cli, kernel
from unixnu.config import Context
from unixnu.util import Error, run

options = ['-D', str(device), '--os', '27', '--out', str(args.out), '-j', '4']
ctx = Context(cli.parser().parse_args(['defconfig', 'sheng_ipados27_defconfig', *options]))
cli.cmd_defconfig(ctx)
ctx = Context(cli.parser().parse_args(['build', 'kernel', *options]))
ctx.logs = args.logs / 'pipeline'
modules = cli.prepare(ctx, ['kernel'])
crypto = args.unixnu / 'scripts/build-corecrypto-14.py'
original_crypto = subprocess.check_output(['git', '-C', args.unixnu, 'show', 'HEAD:scripts/build-corecrypto-14.py'], text=True)
cache_spec = importlib.util.spec_from_file_location('crypto_cache', device / 'scripts/prepare-corecrypto-cache.py')
cache_module = importlib.util.module_from_spec(cache_spec)
cache_spec.loader.exec_module(cache_module)
cached_crypto = cache_module.transform(original_crypto)
if crypto.read_text() not in (original_crypto, cached_crypto):
    raise SystemExit('Unreviewed local CoreCrypto builder edits; retained for inspection')
if crypto.read_text() != cached_crypto:
    crypto.write_text(cached_crypto)
# Assemble again so the tree receives the changed builder, keeping build/.cache.
from unixnu import tree
tree.assemble(ctx, modules)

class StageComplete(Exception):
    pass

def corecrypto_stage(context, env):
    framework = context.tree / '.cache/fakeroot/System/Library/Frameworks/Kernel.framework/Versions/A'
    headers = ('kern/assert.h', 'kern/clock.h', 'pexpert/pexpert.h')
    present = {name: next((str(framework / base / name) for base in ('Headers', 'PrivateHeaders')
                          if (framework / base / name).is_file()), None) for name in headers}
    print('Generated Kernel.framework headers:', json.dumps(present), flush=True)
    if not all(present.values()):
        raise Error('Generated XNU headers missing after real bootstrap')
    bootstrap = context.logs / 'kernel-bootstrap.log'
    text = bootstrap.read_text(errors='replace')
    # Upstream tolerates the deliberate unresolved bootstrap link if a compile
    # record exists. Do not accidentally hide a C/C++ compilation failure.
    errors = [line for line in text.splitlines() if re.search(r'\bfatal error:|\berror:', line)
              and not re.search(r'(?:clang|ld): error: linker command failed', line)]
    if errors:
        raise Error('XNU compile diagnostics before the archive stage:\n' + '\n'.join(errors[-20:]))
    env = dict(env, PATH=kernel.toolchain_path(env.get('PATH')), UNIXNU_DEVICE=str(device))
    for label, extra in [('plain', []), ('namespaced', ['--namespace'])]:
        run(['python3', context.tree / 'scripts/build-corecrypto-14.py', *extra], cwd=context.tree,
            env=env, log_file=context.logs / f'corecrypto-{label}.log')
        print((context.logs / f'corecrypto-{label}.log').read_text(errors='replace')[-5000:], flush=True)
    report = {'stage': 'xnu-bootstrap-and-corecrypto', 'tree': str(context.tree), 'headers': present,
              'xnu_objects': len(list((context.tree / 'build/xnu/ios-obj').rglob('*.o'))),
              'bootstrap_link_deferred': 'Undefined symbols' in text,
              'full_native_link': False, 'prelink': False, 'installation_images': False}
    for path in (context.tree / 'build/corecrypto-2023').glob('*.json'):
        shutil.copy2(path, args.logs / path.name)
    (args.logs / 'stage-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    raise StageComplete

# Use the existing fixed kernel.build bootstrap/header path verbatim. Replace
# only its archive dispatch in this process, then stop before other board
# archives and the final native link. No production recipe is bypassed in package.
kernel.build_archives = corecrypto_stage
os.environ['UNIXNU_XNU_COMPILE_STAGE'] = '1'
try:
    kernel.build(ctx, modules)
except StageComplete:
    print('PASS: real XNU compile/bootstrap and both CoreCrypto archives; full board link remains deferred', flush=True)
