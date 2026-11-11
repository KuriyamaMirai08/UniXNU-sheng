#!/usr/bin/env python3
"""Offline configuration and synthetic image round trips; never an install image.

No real Data seed, device identity, OS disk image, or GPU binary is read. The
firmware volume and kernel are explicit fixtures, so this cannot qualify a real
UEFI firmware, prelinked kernel, runtime addon, or hardware boot.
"""
import argparse
import ast
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unixnu', type=Path, required=True)
    parser.add_argument('--uefi', type=Path, required=True)
    parser.add_argument('--soc', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.unixnu.resolve() / 'scripts'))
    from unixnu.cli import parser as cli_parser
    from unixnu.config import Context
    from unixnu import bootimg, devicetree, payload, pipeline
    from unixnu.util import Error
    device = Path(__file__).resolve().parents[1]
    result = {'synthetic_only': True, 'real_data_accessed': False,
              'real_firmware_compiled': False, 'hardware_tested': False}
    with tempfile.TemporaryDirectory(prefix='unixnu-image-audit-') as temporary:
        scratch = Path(temporary)
        options = cli_parser().parse_args(['status', '-D', str(device), '--os', '27',
                                          '--out', str(scratch), '--uefi', str(args.uefi.resolve()),
                                          '--local-module', 'soc:sm8550=' + str(args.soc.resolve())])
        ctx = Context(options)
        ctx.logs.mkdir(parents=True, exist_ok=True)
        spec = ctx.board['payload']
        line = payload.check_args(spec['kernel_args'])
        lengths = [len(line)] + [len(line + ' ' + extra) for extra in spec.get('install', {}).get('confirm_args', [])]
        if max(lengths) >= pipeline.MAX_COMMAND_LINE:
            raise ValueError('Boot or install command line exceeds the final manifest limit')
        result['command_line_bytes'] = lengths
        result['boot_partition_limit_configured'] = ctx.board['package'].get('boot_partition_bytes')
        dtb = devicetree.compile_hardware(ctx)
        # Public fixture value, never an installation's platform identity.
        adt = devicetree.generate(dtb, ctx.board, unique_chip_id='1', data=True, trust=True,
                                  addon=True, root_policies=True)
        result['adt_bytes'] = len(adt)
        stage = scratch / 'stage'
        root = stage / 'EFI/UniXNU'
        root.mkdir(parents=True)
        config = b'version = 1\n# synthetic audit fixture\n'
        (root / 'unixnu.toml').write_bytes(config)
        image = ctx.work / 'payload/payload.img'
        image.parent.mkdir(parents=True, exist_ok=True)
        payload.write_volume(stage, image, spec['volume'], int(spec['size_mib']))
        recovered = scratch / 'recovered.toml'
        subprocess.run(['mcopy', '-i', str(image), '::/EFI/UniXNU/unixnu.toml', str(recovered)], check=True)
        if recovered.read_bytes() != config:
            raise ValueError('FAT payload content does not round-trip')
        payload.paths(ctx)[2].write_text(json.dumps({'kernel_args': line}))
        values, _, fd_size, _, _ = bootimg.settings(ctx, args.uefi.resolve())
        fd = scratch / 'fixture.fd'
        fd.write_bytes(b'FIXTURE' + bytes(fd_size - 7))
        output = bootimg.build(ctx, args.uefi.resolve(), fd, dtb, image)
        kernel = ctx.work / 'kernel/kernel.macho'
        kernel.parent.mkdir(exist_ok=True)
        kernel.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x100000c, 2, 2, 0, 0, 0, 0))
        files = pipeline.outputs(ctx)
        manifest = pipeline.write_manifest(ctx, {}, [], files)
        pipeline.verify(ctx, files, manifest)
        result.update(payload_bytes=image.stat().st_size, fixture_boot_bytes=output.stat().st_size,
                      header_version=values['header_version'], fd_bytes=fd_size)
        tree = ast.parse((device / 'scripts/build-gop-legacy-display-27.py').read_text())
        additions = [node.right.body for node in ast.walk(tree)
                     if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
                     and isinstance(node.right, ast.IfExp)
                     and isinstance(node.right.body, ast.Constant)
                     and 'Local strong functions' in str(node.right.body.value)]
        # Keep the extraction specific to the real builder's iPadOS-only text.
        if len(additions) != 1:
            raise ValueError('Cannot uniquely find the real iPadOS support definitions')
        support = ast.literal_eval(additions[0])
        header = ('typedef unsigned long uintptr_t; typedef unsigned long size_t; typedef int kern_return_t; '
                  'class IOMemoryDescriptor;\n#define KERN_INVALID_ARGUMENT 4\n')
        consumer = '''
extern "C" void sheng_ethernet_probe(void) __attribute__((weak_import));
extern "C" void sheng_software_aes_probe(void) __attribute__((weak_import));
extern "C" bool ml_static_mfree_prepare(uintptr_t, size_t) __attribute__((weak_import));
extern "C" kern_return_t iokit_physical_descriptor_close_notify(IOMemoryDescriptor *, void (*)(void *), void *) __attribute__((weak_import));
extern "C" void entry() {
 if(sheng_ethernet_probe) sheng_ethernet_probe();
 if(sheng_software_aes_probe) sheng_software_aes_probe();
 if(ml_static_mfree_prepare) ml_static_mfree_prepare(0,0);
 if(iokit_physical_descriptor_close_notify) iokit_physical_descriptor_close_notify(0,0,0);
}
'''
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        flags = ['xcrun', 'clang++', '-target', 'arm64e-apple-ios27.0', '-isysroot', sdk,
                 '-mkernel', '-ffreestanding', '-fno-stack-protector']
        (scratch / 'consumer.cpp').write_text(header + consumer)
        subprocess.run(flags + ['-c', str(scratch / 'consumer.cpp'), '-o', str(scratch / 'consumer.o')], check=True)
        counts = {}
        for mode in ('weak', 'strong'):
            text = support
            if mode == 'weak':
                for kind in ('void', 'bool', 'kern_return_t'):
                    text = text.replace('extern "C" ' + kind, 'extern "C" __attribute__((weak)) ' + kind)
            (scratch / 'support.cpp').write_text(header + text)
            subprocess.run(flags + ['-c', str(scratch / 'support.cpp'), '-o', str(scratch / 'support.o')], check=True)
            exe = scratch / (mode + '.macho')
            subprocess.run(flags + ['-static', '-nostdlib', '-Wl,-kernel,-add_split_seg_info,-e,_entry',
                                    str(scratch / 'consumer.o'), str(scratch / 'support.o'), '-o', str(exe)], check=True)
            blob = exe.read_bytes()
            ncmds, = struct.unpack_from('<I', blob, 16)
            at = 32
            for _ in range(ncmds):
                cmd, length = struct.unpack_from('<II', blob, at)
                if cmd == 0x80000034:
                    fixups, = struct.unpack_from('<I', blob, at + 8)
                    counts[mode], = struct.unpack_from('<I', blob, fixups + 16)
                    break
                at += length
        if counts != {'weak': 4, 'strong': 0}:
            raise ValueError('Unexpected support function import counts: ' + str(counts))
        result['real_support_link_imports'] = counts
        kernel.write_bytes(kernel.read_bytes() + b'tampered')
        try:
            pipeline.verify(ctx, files, manifest)
        except Error:
            result['manifest_rejects_tampering'] = True
        else:
            raise ValueError('Manifest did not reject a changed output')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
