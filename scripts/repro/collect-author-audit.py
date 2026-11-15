#!/usr/bin/env python3
"""Retain actual images, full logs and bounded source/link evidence.

No archived source is executed. The compact package accompanies the complete
build archive and does not replace the original evidence inventory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


BOARD = "out/sheng/ipados-27.0.1-24A446/sheng_ipados27/"


def selected(relative):
    name, parts = relative.name, relative.parts
    key = relative.as_posix()
    if parts[0] == "evidence":
        return True
    if parts[0] == "baseline-evidence":
        return name in ("kernel.py", "native.macho")
    if key.startswith("UniXNU/kits/XnuPrelink/"):
        return relative.suffix in (".py", ".json", ".md")
    if key.startswith("device/scripts/") or key.startswith("device/patches/"):
        return relative.suffix in (".py", ".sh", ".patch", ".json") or name.startswith("series")
    if parts[0] == "device" and name in ("board.toml", "feeds.toml", "unixnu.lock", ".gitmodules"):
        return True
    if key.startswith("device/configs/"):
        return True
    if key.startswith("UniXNU/") and name in ("NativeRamBlock.cpp", "NativeAdrenoPublish.cpp", "build-arm-driver.py",
                                            "build-fileset-release-reference.py", "build-sheng-source-storage.py"):
        return True
    if key in ("out/ipsw/24A446/kernelcache.decompressed", "uefi-sheng/Resources/Configs/sheng.toml"):
        return True
    if name == "SILICIUM_UEFI.fd":
        return True
    if key.startswith(BOARD):
        local = key[len(BOARD):]
        if local in ("package.manifest.json", ".config", "xnu-inputs.json", "xnu-patches.list"):
            return True
        if local.startswith(("boot/", "payload/", "kernel/")):
            return relative.suffix in (".img", ".macho", ".json", ".log", ".py")
        if "logs" in parts:
            return True
        if name in ("mach.development.bcm2837.unstripped.noctf", "mach.release.bcm2837.unstripped.noctf"):
            return True
        if local.startswith("tree/build/xnu/fileset-reference/") and "source" not in parts and "lto-obj" not in parts:
            return name in ("inputs.json", "lto-command.json", "lto-build.log", "native-stubs.c",
                            "missing-real-providers.json", "source-sha256.json", "omitted-unavailable-forced-exports.json")
        if local.startswith("tree/build/sheng-optional-providers/"):
            return True
        if local.startswith("tree/build/") and "xnu" not in parts:
            return relative.suffix in (".json", ".log", ".cpp", ".c", ".h", ".S") or name.startswith("lib") and relative.suffix == ".a"
        if name in ("link.filelist", "nonltolink.filelist", "startup.o.json", "IOPlatformExpert.cpo.json", "version.c"):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.attempt.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows, total = [], 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__") and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root)
            if not selected(relative):
                continue
            size = path.stat().st_size
            total += size
            if total > 2 * 1024**3:
                raise ValueError("Selected evidence exceeds 2 GiB")
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            with destination.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows.append(dict(path=relative.as_posix(), bytes=size, sha256=digest))
    (output / "COLLECTION.json").write_text(json.dumps(dict(files=rows, selected_bytes=total,
                                                         complete_build_archive_separate=True,
                                                         links_followed=False, device_operations=False), indent=2) + "\n")
    print(json.dumps(dict(files=len(rows), selected_bytes=total, device_operations=False)))


if __name__ == "__main__":
    main()
