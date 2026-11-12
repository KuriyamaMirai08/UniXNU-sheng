#!/usr/bin/env python3
"""Apply pinned Ath12k fetch and XNU header-bootstrap compatibility fixes.

Mesa/prelink validation and the reference, Cargo and Ninja input checks remain
enabled. No tree traversal, ignored patch failures, or file-existence reuse.
"""
import argparse
import ast
from pathlib import Path
import subprocess

UNIXNU = '97437dcf7389484a0eeaa8067725ce743aff18ef'
ATH12K = '48e23bf15fc21bbd30d5583b42b9c09ad65537db'
OLD = ('        subprocess.run(["git", "clone", "--depth", "1", "--branch", source["ref"],\n'
       '                        "--filter=blob:none", "--sparse", source["url"], str(directory)], check=True)')
NEW = '''        urls = [source["url"]]
        if "git.kernel.org" in source["url"]:
            urls.append(source["url"].replace("https://git.kernel.org/", "https://kernel.googlesource.com/"))
        for attempt in range(4):
            url = urls[attempt % len(urls)]
            try:
                import shutil as _shutil
                _shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", "-q", str(directory)], check=True)
                subprocess.run(["git", "-C", str(directory), "sparse-checkout", "set", "--no-cone", *source["paths"]], check=True)
                subprocess.run(["git", "-C", str(directory), "fetch", "--depth", "1", "--filter=blob:none", url, source["commit"]], check=True)
                subprocess.run(["git", "-C", str(directory), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
                break
            except Exception:
                if attempt == 3:
                    raise'''


def transform(source):
    if source.count(OLD) != 1 or source.count('"sparse-checkout", "add"') != 1:
        raise ValueError('Pinned Ath12k fetcher changed; review before adapting it')
    result = source.replace(OLD, NEW).replace('"sparse-checkout", "add"', '"sparse-checkout", "set", "--no-cone"')
    ast.parse(result)
    return result


# A restored XNU object/compile-record cache does not include the generated
# Kernel.framework headers on a fresh macOS runner. Without those headers,
# corecrypto-2023 fails hundreds of source compiles even though startup.o.json
# exists. Bootstrap must run to install the SDK headers before archive recipes.
KERNEL_BOOTSTRAP_ORIGINAL = "    if not record.is_file():\n"
KERNEL_BOOTSTRAP_FIXED = """    framework = ctx.tree / '.cache/fakeroot/System/Library/Frameworks/Kernel.framework/Versions/A'
    required = ('kern/assert.h', 'kern/clock.h', 'pexpert/pexpert.h')
    missing_headers = [name for name in required if not any(
        (framework / root / name).is_file() for root in ('Headers', 'PrivateHeaders'))]
    stamp = ctx.tree / '.cache/fakeroot' / ('.xnu-' + env.get('UNIXNU_XNU_VERSION', '10063.141.1') + '-headers')
    if missing_headers and stamp.is_file():
        stamp.unlink()  # An incomplete restored header cache must not skip installhdrs.
    if not stamp.is_file():
        missing_headers.append('XNU installhdrs stamp')
    if missing_headers:
        log('kernel: missing generated XNU headers; forcing bootstrap: ' + ', '.join(missing_headers))
    if not record.is_file() or missing_headers:
"""


def transform_kernel_bootstrap(source):
    # The pinned kernel.py has two such checks: the bootstrap entry condition
    # and the post-failure validation. Modify only the first; retain the guard.
    marker = "    record = ctx.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'\n"
    if source.count(marker) != 1 or source.count(KERNEL_BOOTSTRAP_ORIGINAL) != 2:
        raise ValueError('Pinned kernel bootstrap source changed; review before adapting it')
    start = source.index(marker) + len(marker)
    if not source.startswith(KERNEL_BOOTSTRAP_ORIGINAL, start):
        raise ValueError('Unexpected bootstrap condition after startup compile record')
    result = source[:start] + KERNEL_BOOTSTRAP_FIXED + source[start + len(KERNEL_BOOTSTRAP_ORIGINAL):]
    ast.parse(result)
    return result


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unixnu', required=True, type=Path)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    ath = device / 'drivers/Ath12kWifi'
    for path, expected in ((args.unixnu, UNIXNU), (ath, ATH12K)):
        if git(path, 'rev-parse', 'HEAD') != expected:
            raise SystemExit(f'Unexpected source revision: {path}')
    original = subprocess.check_output(['git', '-C', str(ath), 'show', 'HEAD:tools/fetch-sources.py'], text=True)
    fixed = transform(original)
    path = ath / 'tools/fetch-sources.py'
    current = path.read_text()
    if current not in (original, fixed):
        raise SystemExit('Ath12k fetcher has unreviewed local modifications')
    if current != fixed:
        path.write_text(fixed)
    kernel_path = args.unixnu / 'scripts/unixnu/kernel.py'
    original_kernel = subprocess.check_output(
        ['git', '-C', str(args.unixnu), 'show', 'HEAD:scripts/unixnu/kernel.py'], text=True)
    fixed_kernel = transform_kernel_bootstrap(original_kernel)
    current_kernel = kernel_path.read_text()
    if current_kernel not in (original_kernel, fixed_kernel):
        raise SystemExit('Pinned kernel builder has unreviewed local modifications')
    if current_kernel != fixed_kernel:
        kernel_path.write_text(fixed_kernel)
    print('Prepared pinned Ath12k fetcher and XNU header bootstrap; validation checks remain enabled')


if __name__ == '__main__':
    main()
