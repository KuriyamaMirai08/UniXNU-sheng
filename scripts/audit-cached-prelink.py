#!/usr/bin/env python3
"""Exercise prelink after the package-29 failure, without compiling or using Data.

The four known weak self-bindings are converted to equivalent local rebases in
a diagnostic COPY. This predicts downstream errors; it is not a rebuilt kernel
and must never be published or booted. The source cache is read-only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import tomllib

NATIVE29 = '6fddf022b48fbf1e73a9ce60738607e3f08377938ed904a6792595c40a7550f8'
KNOWN = {'_iokit_physical_descriptor_close_notify', '_sheng_ethernet_probe',
         '_sheng_software_aes_probe', '_ml_static_mfree_prepare'}


def diagnostic_rebases(data, image_class):
    if hashlib.sha256(data).hexdigest() != NATIVE29:
        raise ValueError('Require the exact package-29 native executable')
    image = image_class(data)
    data = bytearray(data)
    command = image.command(0x80000034)
    start, = struct.unpack_from('<I', data, command[0] + 8)
    _, starts, imports, strings, count, fmt, symfmt = struct.unpack_from('<7I', data, start)
    if (count, fmt, symfmt) != (4, 1, 0):
        raise ValueError('Unexpected chained import header')
    defined = {name: va for va, names in image.symbols().items() for name in names}
    names = []
    for i in range(count):
        word, = struct.unpack_from('<I', data, start + imports + i * 4)
        if word & 0x1ff != 0xfd:
            raise ValueError('Expected weak-lookup ordinal -3, not a missing weak import')
        at = start + strings + (word >> 9)
        name = data[at:data.index(0, at)].decode()
        if name not in KNOWN or name not in defined:
            raise ValueError('Unexpected or undefined import: ' + name)
        names.append(name)
    if set(names) != KNOWN:
        raise ValueError('Duplicate or missing expected import')
    table = start + starts
    segments, = struct.unpack_from('<I', data, table)
    bindings = []
    for index in range(segments):
        relative, = struct.unpack_from('<I', data, table + 4 + index * 4)
        if not relative:
            continue
        entry = table + relative
        _, page_size, pointer_format, segment_offset, _, pages = struct.unpack_from('<IHHQIH', data, entry)
        if pointer_format != 7:
            raise ValueError('Expected ARM64E_KERNEL pointers')
        for page, first in enumerate(struct.unpack_from(f'<{pages}H', data, entry + 22)):
            if first == 0xffff:
                continue
            if first & 0x8000:
                raise ValueError('Unexpected multi-start page')
            site = image.base + segment_offset + page * page_size + first
            while True:
                at = image.offset(site, 8)
                word, = struct.unpack_from('<Q', data, at)
                if word >> 62 & 1:
                    if not word >> 63 or word & 0xffff >= len(names):
                        raise ValueError('Unexpected non-authenticated binding or ordinal')
                    name = names[word & 0xffff]
                    target = defined[name] - image.base
                    if not 0 <= target < 1 << 32:
                        raise ValueError('Local target is outside ARM64E auth-rebase range')
                    rebased = (word & ~((1 << 62) | 0xffffffff)) | target
                    struct.pack_into('<Q', data, at, rebased)
                    bindings.append({'name': name, 'site': hex(site), 'target': hex(defined[name])})
                step = word >> 51 & 0x7ff
                if not step:
                    break
                site += step * 4
    if len(bindings) != 4 or {b['name'] for b in bindings} != KNOWN:
        raise ValueError('Expected exactly the four known binding sites')
    struct.pack_into('<I', data, start + 16, 0)
    image_class(data).fixups()  # Exercise the real parser, with all rebases.
    return bytes(data), bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unixnu', required=True, type=Path)
    parser.add_argument('--cache-tree', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    upstream, cached, out = args.unixnu.resolve(), args.cache_tree.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(upstream / 'scripts'), str(upstream / 'kits/XnuPrelink')]
    from kc_image import Image
    from unixnu import ipsw, kernel, profiles
    device = Path(__file__).resolve().parents[1]
    profile = tomllib.loads((upstream / 'profiles/os/ipados-27.0.1-24A446/profile.toml').read_text())
    board = tomllib.loads((device / 'board.toml').read_text())
    effective = profiles.merge(profile, board)
    effective = profiles.merge(effective, board['os_overrides']['ipados-27.0.1-24A446'])
    ctx = SimpleNamespace(board=effective, out_root=out, option_text=lambda *unused: None)
    native = cached / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
    reference = cached / 'build/xnu/fileset-reference/mach.release.bcm2837.unstripped.noctf'
    simulated, bindings = diagnostic_rebases(native.read_bytes(), Image)
    diagnostic = out / 'DIAGNOSTIC-DO-NOT-BOOT.macho'
    diagnostic.write_bytes(simulated)
    cache = ipsw.kernelcache(ctx, ipsw.Ipsw(ctx))
    roots = effective['kernel']['prelink']['roots']
    command = [sys.executable, str(upstream / 'kits/XnuPrelink/emit_prelink.py'),
               '--kernel', str(diagnostic), '--prelinked', str(cache), '--fileset-reference', str(reference),
               '--slide=' + effective['kernel']['prelink']['slide'],
               '--allow-missing', '--early-security-init', effective['kernel']['prelink']['early_security_init'],
               '--output', str(out / 'DIAGNOSTIC-prelinked.macho')]
    for root in roots:
        command += ['--root', root]
    summary = {'diagnostic_only': True, 'rebases': bindings, 'roots': roots,
               'native_original_sha256': NATIVE29, 'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest()}
    try:
        with (out / 'prelink.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=720)
        summary['prelink_exit'] = result.returncode
        report = out / 'DIAGNOSTIC-prelinked.json'
        if report.is_file():
            record = json.loads(report.read_text())
            summary['candidate_bytes'] = record.get('candidate_bytes')
            summary['missing'] = record.get('missing')
            summary['stubbed'] = record.get('stubbed')
            policy = json.loads((upstream / 'scripts/policies/ipados-27.0.1-24A446/prelink-regression.json').read_text())
            try:
                kernel.check_prelink_regressions(record, policy)
                summary['regression_policy'] = 'pass'
            except Exception as error:
                summary['regression_policy'] = str(error)
        print((out / 'prelink.log').read_text()[-12000:])
    finally:
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        # Keep diagnostic reports; neither simulated image is a deliverable.
        diagnostic.unlink(missing_ok=True)
        (out / 'DIAGNOSTIC-prelinked.macho').unlink(missing_ok=True)
    if summary.get('prelink_exit') != 0 or summary.get('regression_policy') != 'pass':
        raise SystemExit('Audit found a prelink blocker; read summary.json and prelink.log')


if __name__ == '__main__':
    main()
