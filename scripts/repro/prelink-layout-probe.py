#!/usr/bin/env python3
"""Measure the fileset prelink text/data collision boundary.

The production kit raises "Native code would collide with collection data"
without reporting the two addresses or the byte overrun. This read-only probe
runs the same production layout code (kc_image / fileset_emit / fileset_layout)
against a built native kernel and collection image and reports the exact
boundary that the guard compares, plus the authoritative Layout verdict. It
never writes an image, never relocates __DATA and never relaxes the guard.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', required=True,
                        help='XnuPrelink kit directory (produces kc_image et al.)')
    parser.add_argument('--kernel', required=True,
                        help='native unimplemented Mach-O (mach.*.unstripped.noctf)')
    parser.add_argument('--prelinked', required=True,
                        help='collection kernelcache (MH_FILESET)')
    parser.add_argument('--root', action='append', default=[],
                        help='prelink --root value, repeated in order')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    kit = Path(args.kit)
    if not (kit / 'kc_image.py').is_file():
        raise SystemExit(f'kit has no kc_image.py: {kit}')
    sys.path.insert(0, str(kit))
    from kc_image import Image
    import fileset_emit as fe
    from fileset_layout import Layout, align

    cache = Image(Path(args.prelinked).read_bytes())
    native = Image(Path(args.kernel).read_bytes())
    report = dict(kernel=str(args.kernel), prelinked=str(args.prelinked),
                  cache_kind=cache.kind, native_kind=native.kind,
                  native_base=hex(native.base), root_count=len(args.root))
    closure = fe.dependency_closure(cache, args.root)
    report['closure_size'] = len(closure) if closure is not None else None
    cache, slide, dropped = fe.rebase_collection(cache, native.base, closure, None,
                                                 set(args.root))
    report['collection_slide'] = hex(slide)
    report['dropped_entries'] = dropped

    segments = {s['name']: dict(s) for s in cache.segments}
    occupied = []
    for name, (_, offset) in cache.entries.items():
        if name == 'com.apple.kernel' or (closure is not None and name not in closure):
            continue
        for segment in Image(cache.data, offset).segments:
            if segment['size'] and segment['name'] != '__LINKEDIT':
                occupied.append((segment['va'], segment['va'] + segment['size']))
    code = segments['__TEXT_EXEC']
    end_kept = max([code['va']] + [end for begin, end in occupied
                                   if code['va'] <= begin < code['va'] + code['size']])
    native_start = align(end_kept)

    def size_of(name):
        return next(s['size'] for s in native.segments if s['name'] == name)

    text = size_of('__TEXT_EXEC')
    kld = size_of('__KLD')
    kld_start = align(native_start + text)
    code_end = kld_start + kld
    data_va = segments['__DATA']['va']
    report.update(
        text_exec_root_va=hex(code['va']), text_exec_root_size=hex(code['size']),
        end_kept=hex(end_kept), native_text_start=hex(native_start),
        native_text_exec_size=hex(text), kld_size=hex(kld), kld_start=hex(kld_start),
        code_end=hex(code_end), data_va=hex(data_va),
        room_bytes=data_va - native_start, needed_bytes=code_end - native_start,
        overrun_bytes=code_end - data_va, collides=code_end > data_va)

    # Run the authoritative production guard so the probe cannot drift from it.
    try:
        Layout(cache, native, closure)
        report['layout_verdict'] = 'pass'
        report['layout_error'] = None
    except Exception as error:  # noqa: BLE001 - report any guard rejection verbatim
        report['layout_verdict'] = 'fail'
        report['layout_error'] = f'{type(error).__name__}: {error}'

    text_out = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text_out, encoding='utf-8')
    print(text_out)


if __name__ == '__main__':
    main()
