#!/usr/bin/env python3
"""Persistent production XNU compilation, native link or strict prelink; no installation images."""
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
import hashlib
import struct

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--unixnu', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--logs', type=Path, required=True)
p.add_argument('--stage', choices=('xnu-corecrypto', 'native-link', 'prelink'), default='xnu-corecrypto')
args = p.parse_args()
device = Path(__file__).resolve().parents[1]
args.logs.mkdir(parents=True, exist_ok=True)
if args.stage == 'prelink':
    # No archive dispatcher, make, compiler, defconfig rewrite or input prefetch.
    subprocess.run([sys.executable, device / 'scripts/m4-prelink.py', '--unixnu', args.unixnu,
                    '--out', args.out, '--logs', args.logs], check=True)
    raise SystemExit(0)
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
    expected_unresolved_link = ('Undefined symbols for architecture arm64e' in text
                                and 'ld: symbol(s) not found for architecture arm64e' in text)
    errors = [line for line in text.splitlines() if re.search(r'\bfatal error:|\berror:', line)
              and not (expected_unresolved_link and re.search(
                  r'^(?:clang(?:\+\+)?|ld): error: linker command failed', line))]
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
if args.stage == 'native-link':
    # Retain the original ordered archive dispatcher and final native make.
    # Existing startup records and generated headers avoid another bootstrap.
    os.environ.pop('UNIXNU_XNU_COMPILE_STAGE', None)
    os.environ['UNIXNU_ROOT'] = str(args.unixnu.resolve())
    # cli.prepare(kernel) fetches only the bootstrap reference subset. Board
    # archives also consume pinned HID/USB/etc sources normally fetched by
    # release dependency preparation. Fetch sources only, never IPSW/runtime.
    from unixnu import feeds
    feeds.fetch(ctx, modules)
    ath = device / 'drivers/Ath12kWifi'
    if ci.git(ath, 'rev-parse', 'HEAD') != ci.ATH12K:
        raise SystemExit('Unexpected Ath12k source revision')
    ath_original = subprocess.check_output(['git', '-C', ath, 'show', 'HEAD:tools/fetch-sources.py'], text=True)
    ath_fixed = ci.transform(ath_original)
    ath_path = ath / 'tools/fetch-sources.py'
    if ath_path.read_text() not in (ath_original, ath_fixed):
        raise SystemExit('Unreviewed Ath12k fetcher edits; preserved for inspection')
    if ath_path.read_text() != ath_fixed:
        ath_path.write_text(ath_fixed)
    # The actual M4 attempt timed out while reading a pinned GPU input.
    # Retry transport failures only; keep all SHA-256/size/blob checks intact.
    fetch_path = args.unixnu / 'scripts/fetch-adreno-inputs.py'
    fetch_original = subprocess.check_output(['git', '-C', args.unixnu, 'show', 'HEAD:scripts/fetch-adreno-inputs.py'], text=True)
    network_old = "        with urllib.request.urlopen(request, timeout=30) as response:\n            data = response.read()"
    network_new = '''        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read()
                break
            except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead) as error:
                print(f'GPU input transport attempt {attempt + 1}/4: {url}: {error}', flush=True)
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)'''
    if fetch_original.count(network_old) != 1:
        raise Error('Pinned GPU fetcher changed; review before adapting')
    fetch_fixed = 'import time, urllib.error, http.client\n' + fetch_original.replace(network_old, network_new)
    ast.parse(fetch_fixed)
    if fetch_path.read_text() not in (fetch_original, fetch_fixed):
        raise Error('Unreviewed GPU fetcher changes retained')
    if fetch_path.read_text() != fetch_fixed:
        fetch_path.write_text(fetch_fixed)
    tree.assemble(ctx, modules)
    plan = [(kind, item['id'] if kind == 'component' else item) for kind, item in kernel.archive_plan(ctx)]
    (args.logs / 'archive-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    print('Production archive plan:', json.dumps(plan), flush=True)
    # These are the source/keyboard prerequisites of the hosted package path,
    # not runtime/Seed preparation. Pre-fetch outside the display sub-build's
    # 300-second compile window, preserving every already verified download.
    for label, command in [
        ('keyboard-input', ['python3', device / 'scripts/extract-files.py', '--section', 'Keyboard', '--device', device]),
        ('wifi-sources', ['bash', ath / 'tools/fetch-sources.sh']),
        ('bluetooth-sources', ['python3', device / 'drivers/QcaBluetooth/tools/prepare-linux.py']),
    ]:
        run(command, cwd=device, log_file=ctx.logs / (label + '.log'))
else:
    kernel.build_archives = corecrypto_stage
    os.environ['UNIXNU_XNU_COMPILE_STAGE'] = '1'
try:
    kernel.build(ctx, modules)
except StageComplete:
    print('PASS: real XNU compile/bootstrap and both CoreCrypto archives; full board link remains deferred', flush=True)
else:
    if args.stage != 'native-link':
        raise Error('CoreCrypto stage did not stop at its expected boundary')
    native = ctx.tree / ctx.board['kernel']['prelink']['kernel']
    blob = native.read_bytes()
    magic, cpu, subtype, filetype = struct.unpack_from('<4I', blob)
    if (magic, cpu, subtype & 0xffffff, filetype) != (0xfeedfacf, 0x100000c, 2, 2):
        raise Error(f'Not an arm64e MH_EXECUTE native kernel: {(magic, cpu, subtype, filetype)}')
    undefined = subprocess.check_output(['xcrun', 'nm', '-u', '-j', native], text=True).strip()
    (args.logs / 'native-undefined.txt').write_text(undefined + '\n')
    if undefined:
        raise Error('Native executable has unresolved symbols: ' + undefined[:2000])
    for label, command in [('native-load-commands', ['xcrun', 'otool', '-hv', '-l', native]),
                           ('native-segments', ['xcrun', 'size', '-m', native])]:
        (args.logs / (label + '.txt')).write_text(subprocess.check_output(command, text=True))
    report = {'stage': 'native-link', 'native': str(native), 'bytes': len(blob),
              'sha256': hashlib.sha256(blob).hexdigest(), 'cpu': cpu, 'subtype': subtype,
              'filetype': 'MH_EXECUTE', 'architecture': 'arm64e', 'undefined_symbols': [],
              'full_native_link': True, 'prelink': False, 'installation_images': False,
              'archives': [str(p.relative_to(ctx.tree)) for p in sorted((ctx.tree / 'build').rglob('*.a'))]}
    (args.logs / 'native-link-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: real arm64e native link and undefined-symbol check', json.dumps(report, indent=2), flush=True)
