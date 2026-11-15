#!/usr/bin/env python3
"""Build a real branch to the retained 24A446 monitor-free Image4 PAL selector.

The original kext performs certificate and policy verification. This archive
contains only the native BTI/B entry and its N_ABS target, like the author's
existing display and USB bindings. Final prelink relocates and checks the branch.
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

from kernel_target import ARCH, TRIPLE, check_object

ROOT = Path(__file__).resolve().parents[1]
CACHE_SHA = "38e6d9fa5f789b8228f4617ef4c6d2a3fd8ab564abdc9b62920f1db53fc1780a"
ENTRY = "com.apple.security.Image4"
SELECTOR = 0xFFFFFE000A9E5230
SELECTOR_SHA = "1a291adcc5f9dc59dc1bd697cf3145109fc6390c8bf9602da0870e353a618690"
PAL = 0xFFFFFE00084779D0
NATIVE_LINK = 0xFFFFFFF007004000
SYMBOL = "_sheng_image4_normal_pal"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(raw):
    from kc_image import Image
    if hashlib.sha256(raw).hexdigest() != CACHE_SHA:
        raise ValueError("Image4 adapter requires the reviewed 24A446 kernelcache")
    cache = Image(raw)
    member = Image(raw, cache.entries[ENTRY][1])
    if hashlib.sha256(member.read(SELECTOR, 64)).hexdigest() != SELECTOR_SHA:
        raise ValueError("Original PAL selector instructions changed")
    fields = cache.fixups().get(PAL + 0x100)
    if fields != (0xFFFFFE000A9E5380, 1, 0, 0x90E1, 0):
        raise ValueError("Normal PAL nonce callback/authentication changed")
    section = member.section(PAL + 0x100)
    if (section["segment"], section["name"]) != ("__DATA_CONST", "__const"):
        raise ValueError("PAL storage no longer has the reviewed early-lockdown contract")
    slide = (NATIVE_LINK - cache.base) & ((1 << 64) - 1)
    return dict(kernelcache_sha256=CACHE_SHA, entry=ENTRY,
                original_selector=hex(SELECTOR), selector_sha256=SELECTOR_SHA,
                collection_base=hex(cache.base), native_link_address=hex(NATIVE_LINK),
                collection_slide=hex(slide), absolute_target=hex((SELECTOR + slide) & ((1 << 64) - 1)),
                normal_pal=hex(PAL), nonce_callback_fields=list(fields),
                native_placement_compensation=False, runtime_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernelcache", type=Path,
                        default=os.environ.get("UNIXNU_KERNELCACHE"))
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    if args.kernelcache is None:
        parser.error("pass the actual --kernelcache or UNIXNU_KERNELCACHE input")
    sys.path.insert(0, str(ROOT / "kits/XnuPrelink"))
    report = inspect(args.kernelcache.read_bytes())
    if args.inspect_only:
        print(json.dumps(report, indent=2))
        return
    if ARCH != "arm64e" or os.environ.get("UNIXNU_IPSW_BUILD") != "24A446":
        parser.error("the adapter belongs only to the reviewed sheng 24A446 arm64e profile")
    out = ROOT / "build/sheng-image4-normal"
    out.mkdir(parents=True, exist_ok=True)
    # Separate objects are necessary: ld must see the unresolved branch and
    # N_ABS definition independently, as in the original board builders.
    sources = {
        "entry": f".section __TEXT,__text,regular,pure_instructions\n.p2align 2\n.globl {SYMBOL}\n{SYMBOL}:\n bti c\n b {SYMBOL}.original\n",
        "target": f".globl {SYMBOL}.original\n.set {SYMBOL}.original, {report['absolute_target']}\n",
    }
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    objects = []
    commands = []
    for name, text in sources.items():
        source, obj = out / (name + ".S"), out / (name + ".o")
        source.write_text(text)
        command = ["xcrun", "clang", "-target", TRIPLE, "-isysroot", sdk,
                   "-c", str(source), "-o", str(obj)]
        commands.append(command)
        with (out / (name + ".log")).open("wb") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        check_object(obj.read_bytes(), name)
        objects.append(obj)
    archive = out / "libShengImage4Normal.a"
    subprocess.run(["xcrun", "ar", "rcs", str(archive), *map(str, objects)], check=True)
    report.update(archive_sha256=digest(archive), source_sha256=digest(Path(__file__)),
                  objects={p.name: digest(p) for p in objects}, commands=commands,
                  certificate_policy_bodies_replaced=False)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(archive)


if __name__ == "__main__":
    main()
