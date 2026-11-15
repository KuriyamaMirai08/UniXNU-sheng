#!/usr/bin/env python3
"""Exercise the actual absent/present branches and Apple's arm64e linker.

Harness providers are test peers only. No harness source or executable is
linked into the kernel or the RELEASE comparison.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def require(value, message):
    if not value:
        raise ValueError(message)


def between(text, begin, end):
    require(text.count(begin) == 1, "Ambiguous actual consumer marker")
    return text[text.index(begin):text.index(end, text.index(begin))]


def verify(tree, output):
    sys.path.insert(0, str(tree / "kits/XnuPrelink"))
    from kc_image import Image
    gpu = tree / "drivers/Adreno740/NativeAdrenoPublish.cpp"
    ram = tree / "drivers/RamBlock/NativeRamBlock.cpp"
    gpu_block = between(gpu.read_text(), "#if SHENG_HAS_PAGER_CLOSE\n        const bool hook=", "        NativeAdrenoPoolNoteView(grant,view->tracked_);")
    ram_block = between(ram.read_text(), "#if SHENG_HAS_PAYLOAD_RELEASE\n  uint32_t release = 0;", "  memcpy(native_ram_block_seed_sha256,seedHash,32);")
    # Use the exact transformed statement blocks, with test-owned types and
    # real side effects. The present case calls the provider; absent does not.
    header = '''#include <stdint.h>
#include <limits.h>
#include <stddef.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef int kern_return_t;
enum {KERN_SUCCESS=0};
struct IOMemoryDescriptor {bool tracked_=false;};
static unsigned pager_calls, release_calls, frees;
static uint32_t native_adreno_pool_views[5], native_ram_block_seed_released;
extern "C" kern_return_t iokit_physical_descriptor_close_notify(IOMemoryDescriptor *,void (*)(void *),void *) {
 ++pager_calls;return KERN_SUCCESS;
}
extern "C" bool ml_static_mfree_prepare(vm_offset_t,vm_size_t) {++release_calls;return true;}
static void NativeAdrenoPoolViewClosed(void *) {}
static bool PE_parse_boot_argn(const char *,uint32_t *value,size_t) {*value=1;return true;}
static uintptr_t ml_static_ptovirt(uintptr_t value) {return value;}
static void IODTFreeLoaderInfo(const char *,void *,int) {++frees;}
'''
    source = header + '''static void exercise() {
 IOMemoryDescriptor object; auto view=&object; void *grant=&object;
''' + gpu_block + '''
 const bool packedInput=true; void *memory=nullptr; const uintptr_t physical=0x200000; const size_t bytes=4096;
''' + ram_block + '''
}
int main() {
 exercise();
#if SHENG_HAS_PAGER_CLOSE && SHENG_HAS_PAYLOAD_RELEASE
 return pager_calls!=1 || release_calls!=1 || frees!=1 || native_adreno_pool_views[4]!=1 || native_ram_block_seed_released!=1;
#else
 return pager_calls || release_calls || frees || native_adreno_pool_views[4] || native_ram_block_seed_released;
#endif
}
'''
    path = output / "actual-branches.cpp"
    path.write_text(source)
    runs = []

    def run(argv, accepted=(0,)):
        result = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
        runs.append(dict(argv=list(map(str, argv)), returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        (output / "commands.json").write_text(json.dumps(runs, indent=2) + "\n")
        require(result.returncode in accepted, "Optional-provider check failed: " + result.stderr[-2000:])
        return result

    for present in (0, 1):
        exe = output / ("present" if present else "absent")
        run(["xcrun", "clang++", "-O2", "-Wno-pointer-bool-conversion",
             "-DSHENG_HAS_PAGER_CLOSE=" + str(present), "-DSHENG_HAS_PAYLOAD_RELEASE=" + str(present), path, "-o", exe])
        run([exe])
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    # Undeclared weak imports are refused by Apple's authenticated kernel link.
    # The audited absent consumer emits neither an import nor a fake definition.
    consumer = '''#ifndef SHENG_HAS_PAGER_CLOSE
#define SHENG_HAS_PAGER_CLOSE 1
#endif
#if SHENG_HAS_PAGER_CLOSE
extern "C" void optional_provider(void) __attribute__((weak_import));
#endif
extern "C" void entry() {
#if SHENG_HAS_PAGER_CLOSE
 if(optional_provider) optional_provider();
#endif
}
'''
    peer = 'extern "C" volatile unsigned provider_calls;\nvolatile unsigned provider_calls;\nextern "C" void optional_provider(void) {provider_calls=provider_calls+1;}\n'
    (output / "consumer.cpp").write_text(consumer)
    (output / "peer.cpp").write_text(peer)
    flags = ["xcrun", "clang++", "-target", "arm64e-apple-ios27.0", "-isysroot", sdk,
             "-mkernel", "-ffreestanding", "-fno-stack-protector", "-O2"]
    run([*flags, "-c", output / "peer.cpp", "-o", output / "peer.o"])
    linked = []
    for mode, enabled in (("absent", 0), ("present", 1)):
        obj = output / (mode + ".o")
        run([*flags, "-DSHENG_HAS_PAGER_CLOSE=" + str(enabled), "-c", output / "consumer.cpp", "-o", obj])
        exe = output / (mode + ".macho")
        run([*flags, "-static", "-nostdlib", "-Wl,-kernel,-add_split_seg_info,-e,_entry", obj,
             *([output / "peer.o"] if enabled else []), "-o", exe])
        image = Image(exe.read_bytes())
        image.fixups()
        symbols = {name for names in image.symbols().values() for name in names}
        require(("_optional_provider" in symbols) == bool(enabled), "Absent/present definition mismatch")
        linked.append(dict(mode=mode, sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                           imports_and_binds_refused_by_unchanged_parser=True, provider_defined=bool(enabled)))
    # Negative: a supposedly enabled capability with no provider must fail,
    # preserving the real-link gate instead of falling back to a placeholder.
    result = subprocess.run([*flags, "-static", "-nostdlib", "-Wl,-kernel,-add_split_seg_info,-e,_entry",
                             str(output / "present.o"), "-o", str(output / "missing.macho")], capture_output=True, text=True)
    runs.append(dict(argv=["negative missing real provider"], returncode=result.returncode,
                     stdout=result.stdout, stderr=result.stderr))
    require(result.returncode != 0 and "optional_provider" in result.stderr, "Missing provider was not refused")
    (output / "commands.json").write_text(json.dumps(runs, indent=2) + "\n")
    result = dict(actual_gpu_consumer_sha256=hashlib.sha256(gpu.read_bytes()).hexdigest(),
                  actual_ram_consumer_sha256=hashlib.sha256(ram.read_bytes()).hexdigest(),
                  actual_statement_blocks_exercised=True, absent_and_present_host_cases_passed=True,
                  apple_arm64e_links=linked, missing_real_provider_negative_refused=True,
                  kernel_or_reference_harness_inputs=False, device_operations=False)
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    print(json.dumps(verify(args.tree.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
