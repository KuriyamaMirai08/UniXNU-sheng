"""Stage 0C-1B: one isolated production ARM64 compile attempt.

This mirrors scripts/repro/run.py up to `unixnu build kernel`, which is the
repository's own supported path for compiling the device source drivers. The
only additions are the reviewed Stage 0A..0B-3B patches applied to the pinned
checkouts before the build, and a bounded collector for the compile evidence.

It never runs the release, never packs a boot image or payload, and never
touches a device. The uploaded evidence is limited to compiler logs, error
summaries and relocatable-object size/hash records.
"""
import hashlib
import json
import re
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from preserve import apply

DEVICE = '1281f0f4eb010da0b3c2d9f1c5684e9566fe318f'
FRAMEWORK = '97437dcf7389484a0eeaa8067725ce743aff18ef'
DRIVER_HELPER_SHA256 = 'e3ca14afe6c14b0745385da7399c4380a90be2237ad331bf64156dde29ddcc73'

# name -> object built by build-sheng-source-storage.py
TARGET_OBJECTS = {
    'NativeUfs.cpp': 'build/sheng-source-storage/NativeUfs.o',
    'NativeRamBlock.cpp': 'build/sheng-source-storage/NativeRamBlock.o',
    'BootLog.c': 'build/sheng-source-storage/BootLog.o',
}

REPO = Path(__file__).resolve().parents[2]
PATCHES = REPO / 'stage0c1b/patches'


def configure_source_paths(device, framework, evidence):
    """Bind archive builders to this attempt's verified framework checkout."""
    device = Path(device).resolve(strict=True)
    framework = Path(framework).resolve(strict=True)
    helper = framework / 'scripts/build-sheng-source-drivers.py'
    if not helper.is_file() or not helper.resolve().is_relative_to(framework):
        raise RuntimeError('Missing or external pinned source-driver helper: ' + str(helper))
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    if digest != DRIVER_HELPER_SHA256:
        raise RuntimeError('Pinned source-driver helper identity mismatch: ' + digest)
    os.environ['UNIXNU_ROOT'] = str(framework)
    os.environ['UNIXNU_DEVICE'] = str(device)
    record = dict(framework_commit=FRAMEWORK, device_commit=DEVICE,
                  UNIXNU_ROOT=str(framework), UNIXNU_DEVICE=str(device),
                  helper=str(helper), helper_sha256=digest)
    (Path(evidence) / 'source-paths.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def apply_patch(root, patch, what):
    if not patch.is_file():
        raise RuntimeError('missing patch: ' + str(patch))
    check = subprocess.run(['git', '-C', str(root), 'apply', '--check', str(patch)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check.returncode:
        raise RuntimeError(f'{what}: patch does not apply:\n' + check.stdout.decode(errors='replace'))
    subprocess.run(['git', '-C', str(root), 'apply', str(patch)], check=True)
    print(f'patched {what} with {patch.name}', flush=True)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def collect_object_evidence(tree, evidence, sources):
    storage = tree / 'build/sheng-source-storage'
    result = {'tree': str(tree), 'targets': {}}
    for source, relative in TARGET_OBJECTS.items():
        row = {'source': str(sources.get(source, source))}
        source_path = sources.get(source)
        if source_path and Path(source_path).is_file():
            row['source_sha256'] = sha256(source_path)
        stem = Path(source).stem
        for candidate in (storage / (stem + '.late.o'), storage / (stem + '.o')):
            if candidate.is_file():
                row['object'] = str(candidate)
                row['object_bytes'] = candidate.stat().st_size
                row['object_sha256'] = sha256(candidate)
                break
        log = storage / (stem + '.log')
        if log.is_file():
            text = log.read_text(errors='replace')
            row['log'] = log.name
            row['warnings'] = sum('warning:' in line for line in text.splitlines())
            row['errors'] = sum('error:' in line for line in text.splitlines())
            row['log_tail'] = text.strip().splitlines()[-4:]
            shutil.copyfile(log, Path(evidence) / ('compile-' + log.name))
        command = storage / (stem + '.command.json')
        if command.is_file():
            row['command'] = json.loads(command.read_text())
        result['targets'][source] = row
    for name in ('report.json',):
        report = storage / name
        if report.is_file():
            shutil.copyfile(report, Path(evidence) / ('storage-' + name))
            result['storage_report'] = json.loads(report.read_text())
    drivers = tree / 'build/sheng-source-drivers/report.json'
    if drivers.is_file():
        shutil.copyfile(drivers, Path(evidence) / 'source-drivers-report.json')
        result['source_drivers_report'] = json.loads(drivers.read_text())
    return result


def probe_prelink_layout(fw, evidence):
    """Report the exact prelink text/data boundary the guard compares.

    The production kit raises "Native code would collide with collection data"
    without printing the two addresses. When the kernel log contains the real
    emit_prelink.py invocation, replay its inputs through the read-only probe so
    the evidence carries the exact overrun instead of an unexplained failure.
    """
    log = evidence / 'kernel.log'
    if not log.is_file():
        return None
    line = next((row for row in log.read_text(errors='replace').splitlines()
                 if 'emit_prelink.py' in row), None)
    if line is None:
        return None
    kernel = re.search(r'--kernel\s+(\S+)', line)
    prelinked = re.search(r'--prelinked\s+(\S+)', line)
    if not kernel or not prelinked:
        return None
    command = [sys.executable, str(REPO / 'scripts/repro/prelink-layout-probe.py'),
               '--kit', str(Path(fw) / 'kits/XnuPrelink'),
               '--kernel', kernel.group(1), '--prelinked', prelinked.group(1),
               '--output', str(evidence / 'prelink-layout-probe.json')]
    for root in re.findall(r'--root\s+(\S+)', line):
        command += ['--root', root]
    result = subprocess.run(command, capture_output=True, text=True)
    (evidence / 'prelink-layout-probe.log').write_text(
        result.stdout + result.stderr)
    return result.returncode


def finalize_evidence(tree, evidence, sources, states):
    """Collect completed objects and compiler errors even when the build failed."""
    result = collect_object_evidence(tree, evidence, sources)
    result['stages'] = [dict(stage=row['stage'], status=row.get('status'),
                             returncode=row.get('returncode')) for row in states]
    result['kernel_stage_passed'] = any(
        row['stage'] == 'kernel' and row.get('status') == 'passed' for row in states)
    (Path(evidence) / 'stage0c1b-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    root = (Path(os.environ['RUNNER_TEMP']) / 'stage0c1b' /
            f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}" / 'current')
    root.mkdir(parents=True, exist_ok=True)
    evidence = root / 'evidence'
    evidence.mkdir()
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        stream.write('STAGE0C1B_ROOT=' + str(root) + '\n')
        stream.write('STAGE0C1B_EVIDENCE=' + str(evidence) + '\n')
    os.environ['PYTHONPATH'] = str(Path(__file__).parent.resolve())
    os.environ['PYTHONUNBUFFERED'] = '1'
    os.environ['RUSTUP_TOOLCHAIN'] = '1.98.0'
    states = []
    sources = {}
    tree = root / 'out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree'
    deadline = time.monotonic() + 280 * 60

    def step(name, argv, cwd=root):
        print('STAGE0C1B stage started: ' + name, flush=True)
        row = dict(stage=name, argv=list(map(str, argv)), cwd=str(cwd), start=time.time(), status='running')
        states.append(row)
        (evidence / 'stages.json').write_text(json.dumps(states, indent=2))
        try:
            with (evidence / (name + '.log')).open('wb') as stream:
                process = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                stop = threading.Event()

                def progress():
                    while not stop.wait(60):
                        path = evidence / (name + '.log')
                        print('STAGE0C1B stage running: ' + name +
                              ' log_bytes=' + str(path.stat().st_size), flush=True)

                thread = threading.Thread(target=progress, daemon=True)
                thread.start()
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    row['timeout'] = True
                    raise RuntimeError('Stage 0C-1B reached its build budget: ' + name)
                finally:
                    stop.set()
                    thread.join()
            row.update(returncode=code, status='passed' if code == 0 else 'failed')
            if code:
                raise RuntimeError('First failed stage: ' + name)
        except BaseException:
            row['status'] = 'failed'
            raise
        finally:
            row['end'] = time.time()
            (evidence / 'stages.json').write_text(json.dumps(states, indent=2))
            print('STAGE0C1B stage ended: ' + name + ' ' + row['status'], flush=True)

    try:
        step('environment', ['bash', '-c',
             'sw_vers; uname -a; sysctl -n hw.memsize hw.ncpu; xcodebuild -version; '
             'xcrun clang --version; xcrun --sdk iphoneos --show-sdk-version; '
             'ld -v; rustc +1.98.0 --version'])
        if shutil.disk_usage(root).free < 12 * 1024 ** 3:
            raise RuntimeError('Less than 12 GiB free before source fetch')
        for key in list(os.environ):
            if key.startswith(('CCACHE_', 'SCCACHE_')) or key in ['CC', 'CXX', 'CFLAGS', 'CXXFLAGS',
                                                                  'LDFLAGS', 'UNIXNU_UNIQUE_CHIP_ID']:
                os.environ.pop(key, None)
        for key in ['TMPDIR', 'XDG_CACHE_HOME', 'CLANG_MODULE_CACHE_PATH', 'CARGO_TARGET_DIR']:
            path = root / 'caches' / key
            path.mkdir(parents=True)
            os.environ[key] = str(path)
        for name, url, sha in [('device', 'KuriyamaMirai08/UniXNU-sheng', DEVICE),
                               ('UniXNU', 'UniXNU/UniXNU', FRAMEWORK)]:
            dest = root / name
            step('init-' + name, ['git', 'init', str(dest)])
            step('fetch-' + name, ['git', '-C', str(dest), 'fetch', '--depth', '1',
                                   'https://github.com/' + url + '.git', sha])
            step('checkout-' + name, ['git', '-C', str(dest), 'checkout', '--detach', sha])
            step('submodules-' + name, ['git', '-C', str(dest), 'submodule', 'update', '--init', '--recursive'])
            step('pins-' + name, ['git', '-C', str(dest), 'submodule', 'status', '--recursive'])
            if subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip() != sha:
                raise RuntimeError('SHA mismatch')
            if any(dest.rglob('local.toml')):
                raise RuntimeError('Undeclared local.toml')
        device = root / 'device'
        fw = root / 'UniXNU'
        configure_source_paths(device, fw, evidence)
        apply_patch(device / 'drivers/ShengUfs', PATCHES / 'shenguFs.patch', 'device/drivers/ShengUfs')
        apply_patch(fw / 'drivers/RamBlock', PATCHES / 'ramblock.patch', 'framework/drivers/RamBlock')
        apply_patch(device, PATCHES / 'bootlog.patch', 'device package/BootLog.c')
        # Record the content actually being compiled.
        sources = {
            'NativeUfs.cpp': device / 'drivers/ShengUfs/NativeUfs.cpp',
            'NativeRamBlock.cpp': fw / 'drivers/RamBlock/NativeRamBlock.cpp',
            'BootLog.c': device / 'package/BootLog.c',
        }
        (evidence / 'patched-source-hashes.json').write_text(json.dumps(
            {name: sha256(path) for name, path in sources.items()}, indent=2) + '\n')
        step('compatibility', ['python3', 'scripts/prepare-package-ci.py', '--unixnu', str(fw)], device)
        apply(fw, evidence)
        common = ['--os', '27', '--out', str(root / 'out'), '--config', str(root / 'build.toml'), '-j', '3']
        (root / 'build.toml').write_text('[build]\n')
        step('dependencies', ['python3', str(fw / 'unixnu'), 'fetch', '-D', str(device), *common])
        step('configuration', ['bash', 'scripts/package.sh', *common, '--no-deps', '--check'], device)
        for name, args in [('firmware', ['python3', 'scripts/extract-files.py']),
                           ('ath12k', ['bash', 'drivers/Ath12kWifi/tools/fetch-sources.sh']),
                           ('bluetooth-source', ['python3', 'drivers/QcaBluetooth/tools/prepare-linux.py']),
                           ('bluetooth-firmware', ['python3', 'scripts/stage-bluetooth-firmware.py',
                                                   '.cache/bt-stage', '--fetch'])]:
            step(name, args, device)
        step('kernel', ['python3', str(fw / 'unixnu'), 'build', 'kernel', '-D', str(device), *common])
    finally:
        build_failed = sys.exc_info()[0] is not None
        collection_error = None
        try:
            finalize_evidence(tree, evidence, sources, states)
        except Exception as error:
            # Preserve the original build failure instead of replacing its
            # traceback with a secondary evidence-collection exception.
            collection_error = error
            (evidence / 'evidence-collection-error.txt').write_text(str(error) + '\n')
        try:
            probe_prelink_layout(fw, evidence)
        except Exception as error:
            (evidence / 'prelink-layout-probe-error.txt').write_text(str(error) + '\n')
        summary = root / 'evidence/stage0c1b-summary.json'
        if not summary.exists():
            (root / 'evidence/stage0c1b-summary.json').write_text(json.dumps(
                {'stages': [(row['stage'], row.get('status'), row.get('returncode')) for row in states]},
                indent=2) + '\n')
        with open(os.environ['GITHUB_ENV'], 'a') as stream:
            stream.write('STAGE0C1B_ROOT=' + str(root) + '\n')
        if collection_error is not None and not build_failed:
            raise collection_error


if __name__ == '__main__':
    main()
