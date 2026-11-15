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
''' + text[end:]
    else:
        raise ValueError("Unknown framework transform: " + name)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unixnu", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    root = args.unixnu.resolve()
    if subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip() != FRAMEWORK:
        raise ValueError("Unexpected framework revision")
    args.evidence.mkdir(parents=True, exist_ok=True)
    records = []
    for name in ("drivers/RamBlock/NativeRamBlock.cpp", "drivers/Adreno740/NativeAdrenoPublish.cpp", "scripts/build-arm-driver.py",
                 "scripts/build-sheng-source-storage.py", "scripts/build-fileset-release-reference.py"):
        path = root / name
        owner = root / "drivers" / name.split("/")[1] if name.startswith("drivers/") else root
        relative = path.relative_to(owner).as_posix()
        original = subprocess.check_output(["git", "-C", owner, "show", "HEAD:" + relative])
        current = path.read_bytes()
        # The reference builder's real-archive CLI patch is applied immediately
        # before these guards and is separately retained in framework-diff.log.
        if current != original and name != "scripts/build-fileset-release-reference.py":
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
