#!/usr/bin/env python3
"""Keep absent optional providers absent in the isolated 24A446 build.

The source guards default to the upstream weak-import behavior. Only the
audited build supplies a header derived from its actual provider selection.
No provider function or successful return is synthesized.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess


FRAMEWORK = "97437dcf7389484a0eeaa8067725ce743aff18ef"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install_reference_verifier(root):
    """Make the builder's real dependency available before author regressions."""
    source = Path(__file__).with_name('reference_diagnostics.py')
    destination = root / 'scripts/reference_diagnostics.py'
    if destination.exists():
        raise ValueError('Unexpected reference verifier already in framework')
    data = source.read_bytes()
    destination.write_bytes(data)
    return dict(path='scripts/reference_diagnostics.py', before_sha256=None,
                after_sha256=sha(data), source='device:scripts/reference_diagnostics.py')


def replace(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError("Missing or ambiguous upstream source: " + label)
    return text.replace(old, new)


def transform(name, text):
    if name == "drivers/RamBlock/NativeRamBlock.cpp":
        text = replace(text,
            'bool ml_static_mfree_prepare(vm_offset_t, vm_size_t) __attribute__((weak_import));',
            '#ifndef SHENG_HAS_PAYLOAD_RELEASE\n#define SHENG_HAS_PAYLOAD_RELEASE 1\n#endif\n'
            '#if SHENG_HAS_PAYLOAD_RELEASE\n'
            'bool ml_static_mfree_prepare(vm_offset_t, vm_size_t) __attribute__((weak_import));\n#endif', name)
        text = replace(text, '  uint32_t release = 0;\n', '#if SHENG_HAS_PAYLOAD_RELEASE\n  uint32_t release = 0;\n', name)
        text = replace(text, '  memcpy(native_ram_block_seed_sha256,seedHash,32);',
                       '#endif\n  memcpy(native_ram_block_seed_sha256,seedHash,32);', name)
    elif name == "drivers/Adreno740/NativeAdrenoPublish.cpp":
        decl = 'extern "C" kern_return_t iokit_physical_descriptor_close_notify(IOMemoryDescriptor *,void (*)(void *),void *) __attribute__((weak_import));'
        text = replace(text, decl,
            '#ifndef SHENG_HAS_PAGER_CLOSE\n#define SHENG_HAS_PAGER_CLOSE 1\n#endif\n'
            '#if SHENG_HAS_PAGER_CLOSE\n' + decl + '\n#endif', name)
        text = replace(text, '        const bool hook=&iokit_physical_descriptor_close_notify!=nullptr;',
                       '#if SHENG_HAS_PAGER_CLOSE\n        const bool hook=&iokit_physical_descriptor_close_notify!=nullptr;', name)
        text = replace(text, '        NativeAdrenoPoolNoteView(grant,view->tracked_);',
            '#else\n'
            '        // The selected kernel has no pager-close provider. Preserve the\n'
            '        // existing untracked-view lifetime and non-reuse policy.\n'
            '        native_adreno_pool_views[4]=0;\n'
            '#endif\n        NativeAdrenoPoolNoteView(grant,view->tracked_);', name)
    elif name == "scripts/build-arm-driver.py":
        text = replace(text, 'from kernel_target import ARCH, TRIPLE, check_object',
                       'from kernel_target import ARCH, TRIPLE, check_object\nfrom sheng_optional_providers import compiler_flags', name)
        text = replace(text, "(out / 'compile-command.json').write_text", "command.extend(compiler_flags(ROOT))\n(out / 'compile-command.json').write_text", name)
    elif name == "scripts/build-sheng-source-storage.py":
        text = replace(text, 'import subprocess\n', 'import subprocess\nfrom sheng_optional_providers import compiler_flags\n', name)
        text = replace(text, "        command = build.compile_command(record, source, output, includes, flags)",
                       "        command = build.compile_command(record, source, output, includes, flags)\n        command += compiler_flags(tree)", name)
    elif name == "scripts/build-fileset-release-reference.py":
        text = replace(text, 'import fnmatch\n',
                       'import fnmatch\nfrom reference_diagnostics import verify_diagnostic_providers\n', name)
        helper = '''
NATIVE_DIAGNOSTIC_SYMBOLS = {
    '___ubsan_handle_add_overflow_minimal',
    '___ubsan_handle_negate_overflow_minimal',
    '___ubsan_handle_sub_overflow_minimal',
    '_mach_assert_jump_key',
}


def prepare_native_diagnostics(source, output):
    """Select XNU's real diagnostics in the private RELEASE comparison only."""
    config = source / 'config/MASTER.arm64.bcm2837'
    before = config.read_bytes()
    expected = 'dba44ba3ab4d913afa315d8c213461f62ee15d894ac71ce1ccee58fd304301ff'
    if hashlib.sha256(before).hexdigest() != expected:
        raise ValueError('Unexpected prepared RELEASE configuration for native archive diagnostics')
    text = before.decode()
    replacements = {
        '#  VM_RELEASE =     [ VM_BASE ]': '#  VM_RELEASE =     [ VM_BASE ubsan_minimal ]',
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError('Missing or ambiguous XNU diagnostic configuration')
        text = text.replace(old, new)
    after = text.encode()
    config.write_bytes(after)
    # MACH_ASSERT changes global kernel structures and enables assertions whose
    # debug-only helpers RELEASE does not build. Select only debug.c's genuine
    # static-key definitions and their complete boot-argument lifecycle.
    debug = source / 'osfmk/kern/debug.c'
    debug_before = debug.read_bytes()
    if hashlib.sha256(debug_before).hexdigest() != 'fd749f59d773dac9cb95f8183ff9dece13f2ae2888f5da6f2efd9197acc9e5b0':
        raise ValueError('Unexpected genuine static-key implementation')
    debug_text = debug_before.decode()
    if debug_text.count('#if MACH_ASSERT\\n') != 2:
        raise ValueError('Unexpected static-key definition/lifecycle guards')
    debug_after = debug_text.replace('#if MACH_ASSERT\\n',
        '#if MACH_ASSERT || XNU_REFERENCE_NATIVE_ASSERT\\n').encode()
    debug.write_bytes(debug_after)
    implementations = {
        name: file_hash(source / name) for name in (
            'san/memory/ubsan_minimal.c', 'san/memory/ubsan_minimal.h',
            'san/conf/files.arm64', 'osfmk/kern/debug.c', 'osfmk/kern/assert.h',
            'osfmk/machine/static_if.h', 'osfmk/kern/startup.c', 'osfmk/arm64/sleh.c')
    }
    record = dict(enabled=True, scope='private RELEASE comparison, not the native kernel',
                  kernel_configs='RELEASE', build_lto=True,
                  added_config_options=['ubsan_minimal'],
                  global_mach_assert_enabled=False,
                  static_key_scope='debug.c definitions and complete feature-override lifecycle',
                  static_key_before_sha256=hashlib.sha256(debug_before).hexdigest(),
                  static_key_after_sha256=hashlib.sha256(debug_after).hexdigest(),
                  config_before_sha256=expected, config_after_sha256=hashlib.sha256(after).hexdigest(),
                  genuine_implementation_sha256=implementations,
                  required_symbols=sorted(NATIVE_DIAGNOSTIC_SYMBOLS),
                  synthesized_providers=False, consumer_instrumentation_disabled=False)
    (output / 'native-archive-diagnostics.json').write_text(json.dumps(record, indent=2) + '\\n')
    return record

'''
        text = replace(text, '\ndef main():\n', '\n' + helper + '\ndef main():\n', name)
        text = replace(text, "    options = parser.parse_args()\n",
            "    parser.add_argument('--native-diagnostics', action='store_true',\n"
            "                        help='select genuine XNU assertion and UBSan providers for DEVELOPMENT archives')\n"
            "    options = parser.parse_args()\n", name)
        text = replace(text, "    mode = 'lto' if options.lto else 'snapshot'\n",
            "    if options.native_diagnostics and not options.lto:\n"
            "        raise ValueError('Native archive diagnostics are qualified only for RELEASE-LTO')\n"
            "    mode = 'lto' if options.lto else 'snapshot'\n", name)
        text = replace(text, "        'mode': mode,\n",
                       "        'mode': mode,\n        'native_diagnostics': options.native_diagnostics,\n"
                       "        'diagnostic_verifier': file_hash(root / 'scripts/reference_diagnostics.py') if options.native_diagnostics else None,\n", name)
        text = replace(text, "    args = ['make','-C',str(source),'build','SDKROOT=iphoneos',\n",
            "    if options.native_diagnostics:\n"
            "        flags += ' -DXNU_REFERENCE_NATIVE_ASSERT=1'\n"
            "    args = ['make','-C',str(source),'build','SDKROOT=iphoneos',\n", name)
        text = replace(text, "        manifest = {str(p.relative_to(source)):",
            "        if options.native_diagnostics:\n            prepare_native_diagnostics(source, output)\n"
            "        manifest = {str(p.relative_to(source)):", name)
        text = replace(text, "    built = output / f'{mode}-obj/RELEASE_ARM64_BCM2837/mach.release.bcm2837.unstripped'\n",
            "    built = output / f'{mode}-obj/RELEASE_ARM64_BCM2837/mach.release.bcm2837.unstripped'\n"
            "    qualification = None\n"
            "    if options.native_diagnostics:\n"
            "        providers = verify_diagnostic_providers(built)\n"
            "        qualification = json.loads((output / 'native-archive-diagnostics.json').read_text())\n"
            "        qualification['final_provider_definitions'] = providers\n"
            "        qualification['final_defined_symbols_verified'] = sorted(NATIVE_DIAGNOSTIC_SYMBOLS)\n"
            "        (output / 'native-archive-diagnostics.json').write_text(json.dumps(qualification, indent=2) + '\\n')\n", name)
        text = replace(text, "'build': str(output)}, indent=2) + '\\n')",
            "'build': str(output), 'native_archive_diagnostics': qualification}, indent=2) + '\\n')", name)
        begin = text.index("    # The bring-up patch calls native hooks")
        end = text.index("    # Forced exports the built objects cannot provide:", begin)
        text = text[:begin] + '''    # The comparison uses real compiled provider archives. Never synthesize
    # data or function placeholders. The first link also names unavailable
    # forced exports as <initial-undefines>; preserve the author's object-based
    # export-list reconciliation before the mandatory final real link.
    build_log = (output / f'{mode}-build.log').read_text()
    missing = sorted(set(re.findall(r'^\\s+"(_[^" ]+)"', build_log, re.M)))
    if result.returncode and missing:
        (output / 'first-link-undefineds.json').write_text(json.dumps(missing, indent=2) + '\\n')
    filelist = output / f'{mode}-obj/RELEASE_ARM64_BCM2837' / ('nonltolink.filelist' if options.lto else 'link.filelist')
    if result.returncode and not filelist.is_file():
        # A compiler failure has no final link inputs to reconcile. Preserve
        # the actual build exit rather than masking it with FileNotFoundError.
        raise SystemExit(result.returncode)
''' + text[end:]
    else:
        raise ValueError("Unknown framework transform: " + name)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unixnu", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--stage0c1f-patched-ramblock", action="store_true")
    args = parser.parse_args()
    root = args.unixnu.resolve()
    if subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip() != FRAMEWORK:
        raise ValueError("Unexpected framework revision")
    args.evidence.mkdir(parents=True, exist_ok=True)
    records = [install_reference_verifier(root)]
    for name in ("drivers/RamBlock/NativeRamBlock.cpp", "drivers/Adreno740/NativeAdrenoPublish.cpp", "scripts/build-arm-driver.py",
                 "scripts/build-sheng-source-storage.py", "scripts/build-fileset-release-reference.py"):
        path = root / name
        owner = root / "drivers" / name.split("/")[1] if name.startswith("drivers/") else root
        relative = path.relative_to(owner).as_posix()
        original = subprocess.check_output(["git", "-C", owner, "show", "HEAD:" + relative])
        current = path.read_bytes()
        # The reference builder's real-archive CLI patch is applied immediately
        # before these guards and is separately retained in framework-diff.log.
        if name == "drivers/RamBlock/NativeRamBlock.cpp" and args.stage0c1f_patched_ramblock:
            if sha(current) != "3594cf762cf0914583157f7c1ccbf510eda70c188082d20524d87f4d769956ac":
                raise ValueError("Stage 0C-1F RamBlock identity changed")
        elif current != original and name != "scripts/build-fileset-release-reference.py":
            raise ValueError("Unreviewed source modification: " + name)
        if name == "scripts/build-fileset-release-reference.py" and sha(current) != "28abed8c005825a8b22a729239f1e330b385271c4bb4289f9008b0b8c7289b47":
            raise ValueError("Reference builder differs from the exact real-archive CLI patch")
        updated = transform(name, current.decode()).encode()
        patch = ''.join(difflib.unified_diff(current.decode().splitlines(True), updated.decode().splitlines(True),
                                            fromfile="a/" + name, tofile="b/" + name))
        (args.evidence / (path.stem + ".optional.patch")).write_text(patch, encoding="utf-8", newline="\n")
        path.write_bytes(updated)
        records.append(dict(path=name, before_sha256=sha(current), upstream_sha256=sha(original), after_sha256=sha(updated),
                            owner_revision=subprocess.check_output(["git", "-C", owner, "rev-parse", "HEAD"], text=True).strip()))
    (args.evidence / "optional-source-transforms.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print("Applied source guards; no optional function definitions were added")


if __name__ == "__main__":
    main()
