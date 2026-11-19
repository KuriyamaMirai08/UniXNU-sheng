#!/usr/bin/env python3
"""Build and strictly prelink a fresh Stage 0C-1F kernel on hosted ARM64 macOS."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

from preserve import apply as preserve

SOURCE = Path(__file__).resolve().parents[2]
DEVICE = "a9f0500af098f8aee87c86a571638daee92caf26"
FRAMEWORK = "97437dcf7389484a0eeaa8067725ce743aff18ef"
UEFI = "66421cb7bb5694843aec8de1ca3d1de4c20cca38"
PATCHES = {
    "shenguFs.patch": "31d8e5539e5e390785b871c09e380e117cdac7c06c867f230444a933818a1b2e",
    "ramblock.patch": "49e36f20899f7500e3c3a2cd4e64e0450c55f05b7a6e24edd84a3ef0a2bf857e",
    "bootlog.patch": "9db2391d1c1e347341911527e4fc1a3caf0fa43f72496bc20c42c6e3af4de896",
    "separate-native-data.patch": "8aec8c51bb901b6e1eca26e0e33092490102998394ad5e46248e4970edf19496",
}
SOURCE_HASHES = {
    "drivers/ShengUfs/NativeUfs.cpp": "08e91b6218d46564f1f635bd4fd3df0af11b3d7e57b2786bff91dee06afea278",
    "drivers/RamBlock/NativeRamBlock.cpp": "3594cf762cf0914583157f7c1ccbf510eda70c188082d20524d87f4d769956ac",
    "package/BootLog.c": "b6c4141705ac1eda9c66b19e0b201d35eb32f8a2110f6f5952e920a5d65268b9",
}
ARCHIVES = {
    "76f8549e40c2657ec71149b82b83c696d3ccfeefcc00d8742e409cad67d5a01b",
    "f9328464d2f664a2b526a0d91bd3f35659cdfd9e2f26a5fa7696cf5f40c442ba",
}
NATIVE = "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf"
REFERENCE = "build/xnu/fileset-reference/mach.release.bcm2837.unstripped.noctf"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(path, expected):
    actual = digest(path)
    require(actual == expected, f"Identity mismatch for {path.name}: {actual} != {expected}")
    return actual


def extract_baseline(archive, destination, contract):
    archive_hash = digest(archive)
    require(archive_hash in ARCHIVES, "Historical archive identity changed")
    expected = {"native.macho": contract["inputs"]["native"],
                "kernel.py": contract["regression_source_sha256"]}
    found = set()
    with tarfile.open(archive, "r|gz") as source:
        for entry in source:
            name = entry.name.removeprefix("./")
            if not entry.isfile():
                continue
            for output, suffix in (("native.macho", "/mach.development.bcm2837.unstripped.noctf"),
                                   ("kernel.py", "/scripts/unixnu/kernel.py")):
                if name == "baseline-evidence/" + output or name.endswith(suffix):
                    data = source.extractfile(entry).read()
                    if hashlib.sha256(data).hexdigest() == expected[output]:
                        (destination / output).write_bytes(data)
                        found.add(output)
                    break
    require(found == expected.keys(), "Historical archive lacks exact baseline native or regression source")
    return dict(archive_sha256=archive_hash, **{name: exact(destination / name, value)
                                               for name, value in expected.items()})


def macho_info(path, filetype=2):
    with path.open("rb") as stream:
        header = stream.read(32)
        magic, cpu, subtype, kind, count, length, _, _ = struct.unpack("<8I", header)
        require(magic == 0xfeedfacf and cpu == 0x0100000c and (subtype & 0xffffff) == 2 and kind == filetype,
                f"Expected ARM64e Mach-O of file type {filetype}")
        commands = stream.read(length)
    offset, segments = 0, {}
    for _ in range(count):
        command, size = struct.unpack_from("<II", commands, offset)
        require(size >= 8 and offset + size <= len(commands), "Invalid native load-command range")
        if command == 0x19:
            name, address, vm_size = struct.unpack_from("<16sQQ", commands, offset + 8)
            segments[name.rstrip(b"\0").decode()] = dict(va=hex(address), vmsize=hex(vm_size))
        offset += size
    require(offset == len(commands), "Incomplete Mach-O load commands")
    if filetype == 2:
        require({"__TEXT_EXEC", "__KLD", "__DATA"} <= segments.keys(), "Incomplete native kernel segments")
    return dict(sha256=digest(path), bytes=path.stat().st_size, segments=segments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-archive", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--public-evidence", required=True, type=Path)
    args = parser.parse_args()
    require(platform.system() == "Darwin" and platform.machine() == "arm64",
            "Stage 0C-1F requires ARM64 macOS")
    require(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "Only the first CI attempt is permitted")
    root = args.scratch.resolve()
    root.mkdir()
    evidence = args.public_evidence.resolve()
    evidence.mkdir(exist_ok=False)
    private = root / "diagnostics"
    private.mkdir()

    def save(name, value):
        (evidence / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def step(name, argv, cwd=root):
        print("Stage 0C-1F:", name, flush=True)
        with (private / (name + ".log")).open("wb") as stream:
            result = subprocess.run(list(map(str, argv)), cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        log = private / (name + ".log")
        with log.open("rb") as stream:
            lines = list(line for line in stream if b"error:" in line or b"Traceback" in line)
        save("last-stage.json", dict(stage=name, exit_code=result.returncode,
                                     log_sha256=digest(log), log_bytes=log.stat().st_size,
                                     diagnostic_lines=len(lines)))
        require(result.returncode == 0, "Failed build stage: " + name)

    def git(root, *arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()

    def patch(name, path, owner):
        command = ["git", "-c", "core.autocrlf=false", "apply"]
        step(name + "-check", [*command, "--check", path], owner)
        step(name, [*command, path], owner)

    for key in list(os.environ):
        if key.startswith(("CCACHE_", "SCCACHE_")) or key in {
            "CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS", "BASH_ENV", "UNIXNU_UNIQUE_CHIP_ID",
            "SHENG_CANDIDATE_DATA", "UNIXNU_DATA_SEED",
        }:
            os.environ.pop(key, None)
    for key in ("TMPDIR", "XDG_CACHE_HOME", "CLANG_MODULE_CACHE_PATH", "CARGO_TARGET_DIR"):
        location = root / key
        location.mkdir()
        os.environ[key] = str(location)
    os.environ.update(PYTHONUNBUFFERED="1", RUSTUP_TOOLCHAIN="1.98.0", ZERO_AR_DATE="1",
                      UNIXNU_SHENG_BOOT_CANDIDATE="1", UNIXNU_SHENG_AUTHOR_AUDIT="1")

    def version(*argv):
        return subprocess.check_output(argv, text=True).strip()

    compiler = Path(version("xcrun", "--sdk", "iphoneos", "--find", "clang"))
    linker = Path(version("xcrun", "--find", "ld"))
    toolchain = dict(xcode=version("xcodebuild", "-version"), clang=version(str(compiler), "--version"),
                     sdk=version("xcrun", "--sdk", "iphoneos", "--show-sdk-version"),
                     linker=version("xcrun", "ld", "-version_details"),
                     rust=version("rustc", "+1.98.0", "--version"), macos=version("sw_vers", "-productVersion"),
                     macos_build=version("sw_vers", "-buildVersion"), runner_image=os.environ.get("ImageVersion"),
                     llvm=version("/opt/homebrew/opt/llvm/bin/llvm-objcopy", "--version"),
                     lld=version("/opt/homebrew/opt/lld/bin/ld64.lld", "--version"),
                     compiler_sha256=digest(compiler), apple_ld_sha256=digest(linker))
    save("toolchain.json", toolchain)
    require(toolchain["xcode"] == "Xcode 26.6\nBuild version 17F113" and toolchain["sdk"] == "26.5"
            and toolchain["macos_build"] == "25G332" and "1267" in toolchain["linker"]
            and "clang-2100.1.1.101" in toolchain["clang"] and toolchain["rust"].startswith("rustc 1.98.0 ")
            and "LLVM version 23.1.4" in toolchain["llvm"] and re.search(r"\bLLD 23\.1\.4\b", toolchain["lld"])
            and toolchain["compiler_sha256"] == "d2e4bf622758eee1bf7267c060497fb2c41e098d37b0fca8be73898dc7e14eda",
            "Run 41 toolchain drift")

    contract = json.loads((SOURCE / "scripts/clean-prelink-contract.json").read_bytes())
    baseline = root / "baseline"
    baseline.mkdir()
    identities = extract_baseline(args.baseline_archive, baseline, contract)
    os.environ.update(UNIXNU_SHENG_BASELINE_NATIVE=str(baseline / "native.macho"),
                      UNIXNU_SHENG_REGRESSION_SOURCE=str(baseline / "kernel.py"))
    assets = SOURCE / "patches/stage0c1f"
    identities["patches"] = {name: exact(assets / name, value) for name, value in PATCHES.items()}
    save("inputs.json", identities)
    for name, repo, revision in (("device", "KuriyamaMirai08/UniXNU-sheng", DEVICE),
                                 ("UniXNU", "UniXNU/UniXNU", FRAMEWORK),
                                 ("uefi-sheng", "UniXNU/uefi-sheng", UEFI)):
        dest = root / name
        step("init-" + name, ["git", "init", dest])
        step("fetch-" + name, ["git", "fetch", "--depth=1", "https://github.com/" + repo + ".git", revision], dest)
        step("checkout-" + name, ["git", "checkout", "--detach", revision], dest)
        if name != "uefi-sheng":
            step("submodules-" + name, ["git", "submodule", "update", "--init", "--recursive"], dest)
        require(git(dest, "rev-parse", "HEAD") == revision and not any(dest.rglob("local.toml")),
                "Unexpected checkout or local source overrides")
    device, framework, uefi = root / "device", root / "UniXNU", root / "uefi-sheng"
    identities["commits"] = dict(device=DEVICE, framework=FRAMEWORK, uefi=UEFI,
                                 experiment=git(SOURCE, "rev-parse", "HEAD"))
    require(git(device / "drivers/ShengUfs", "rev-parse", "HEAD") == "b11de87c234cf4b8f80a8160fb15e6f37a8e5d0c",
            "Unexpected ShengUfs revision")
    require(git(framework / "drivers/RamBlock", "rev-parse", "HEAD") == "737f6dae119ef11990e77dc06bcead945098865e",
            "Unexpected RamBlock revision")
    identities["source_helper_sha256"] = exact(framework / "scripts/build-sheng-source-drivers.py",
                                               "e3ca14afe6c14b0745385da7399c4380a90be2237ad331bf64156dde29ddcc73")
    os.environ.update(UNIXNU_ROOT=str(framework), UNIXNU_DEVICE=str(device), UNIXNU_UEFI=str(uefi))
    for path in ("board.toml", "scripts/sheng-strict-prelink.py", "scripts/clean_prelink_recovery.py",
                 "scripts/prepare-sheng-author-audit.py"):
        shutil.copyfile(SOURCE / path, device / path)
    patch("shengufs", assets / "shenguFs.patch", device / "drivers/ShengUfs")
    patch("ramblock", assets / "ramblock.patch", framework / "drivers/RamBlock")
    patch("bootlog", assets / "bootlog.patch", device)
    identities["patched_sources"] = {name: exact((framework if name.startswith("drivers/RamBlock/") else device)
                                                 / name, value) for name, value in SOURCE_HASHES.items()}
    save("inputs.json", identities)
    kit = framework / "kits/XnuPrelink"
    for name, value in contract["engine"].items():
        exact(kit / name, value)
    for name, value in contract["engine_fixtures"].items():
        exact(kit / "fixtures" / name, value)
    patch("engine-layout", assets / "separate-native-data.patch", kit)
    wrapper = SOURCE / "scripts/sheng-strict-prelink.py"
    step("strict-engine-pins", [sys.executable, "-B", "-c",
         "import runpy,sys,json; from pathlib import Path; p=Path(sys.argv[1]); "
         "sys.path.insert(0,str(p.parent)); m=runpy.run_path(str(p)); "
         "contract=json.loads(p.with_name('clean-prelink-contract.json').read_bytes()); "
         "m['check_kit'](Path(sys.argv[2]),m['engine_contract'](contract,'separate-native-data'))",
         wrapper, kit])
    step("compatibility", [sys.executable, "scripts/prepare-package-ci.py", "--unixnu", framework], device)
    preserve(framework, private)
    patch("reference-builder", device / "patches/build/sheng-reference-archive.patch", framework)
    step("optional-providers", [sys.executable, "scripts/prepare-sheng-author-audit.py", "--unixnu", framework,
                                "--evidence", private, "--stage0c1f-patched-ramblock"], device)
    step("engine-regressions", [sys.executable, "-B", "-m", "unittest", "test_fileset_emit",
                                "test_fileset_layout", "test_fileset_match", "test_fileset_shape"], kit)
    step("reference-builder-regressions", [sys.executable, "scripts/test-fileset-reference.py", "-v"], framework)
    step("reference-regressions", [sys.executable, "scripts/test-author-audit-reference.py",
                                  "--builder", framework / "scripts/build-fileset-release-reference.py"], device)
    config = root / "build.toml"
    config.write_text("[build]\n")
    common = ["-D", device, "--os", "27", "--out", root / "out", "--config", config, "--uefi", uefi, "-j", "3"]
    cli = [sys.executable, framework / "unixnu"]
    step("dependencies", [*cli, "fetch", *common])
    step("configuration", [*cli, "defconfig", "sheng_ipados27_defconfig", *common])
    step("kernelcache", [*cli, "ipsw", "fetch", "KernelCache", *common])
    cache = root / "out/ipsw/24A446/kernelcache.decompressed"
    identities["kernelcache_sha256"] = exact(cache, contract["inputs"]["kernelcache"])
    save("inputs.json", identities)
    os.environ["UNIXNU_KERNELCACHE"] = str(cache)
    for name, command in (
        ("touch-firmware", [sys.executable, "scripts/extract-files.py"]),
        ("ath12k", ["bash", "drivers/Ath12kWifi/tools/fetch-sources.sh"]),
        ("bluetooth-source", [sys.executable, "drivers/QcaBluetooth/tools/prepare-linux.py"]),
        ("bluetooth-firmware", [sys.executable, "scripts/stage-bluetooth-firmware.py", ".cache/bt-stage", "--fetch"]),
        ("stock-firmware", [sys.executable, "scripts/download-sheng-firmware.py", "--connections", "16"]),
        ("extract-stock-firmware", [sys.executable, "scripts/extract-sheng-firmware.py", "--delete-archive"]),
    ):
        step(name, command, device)
    step("assemble-tree", [*cli, "tree", *common])
    work = root / "out/sheng/ipados-27.0.1-24A446/sheng_ipados27"
    tree = work / "tree"
    require(not any(path.is_file() and (path.suffix in (".o", ".a", ".cpo") or path.name == "kernel.macho")
                    for path in tree.rglob("*")), "Precompiled objects exist before kernel build")
    require(not (tree / NATIVE).exists() and not (tree / REFERENCE).exists(), "Stale linked kernel")
    step("optional-provider-link-checks", [sys.executable, "scripts/check-sheng-optional-providers.py",
                                          "--tree", tree, "--output", private / "optional-link"], device)
    output = work / "kernel/kernel.macho"
    try:
        step("kernel-and-strict-prelink", [*cli, "build", "kernel", *common])
    finally:
        objects = {}
        for name in ("NativeUfs.late.o", "NativeRamBlock.late.o", "BootLog.o"):
            path = tree / "build/sheng-source-storage" / name
            if path.is_file():
                objects[name] = dict(bytes=path.stat().st_size, sha256=digest(path))
        save("objects.json", objects)
        if (tree / NATIVE).is_file():
            save("native.json", macho_info(tree / NATIVE))
        failed = output.with_suffix(".failed.json")
        receipts = list(output.parent.glob(".prelink-*/.sheng-evidence-*/receipt.json"))
        if len(receipts) == 1:
            diagnostic = json.loads(receipts[0].read_bytes())
            if diagnostic["status"] == "refused":
                save("strict-failure-stage.json", dict(status=diagnostic["status"], error_type=diagnostic.get("error_type"),
                     message=diagnostic.get("error"), placement=diagnostic["native_data_placement"]))
        if failed.is_file():
            record = json.loads(failed.read_bytes())
            stats = record["statistics"]
            save("strict-refused.json", dict(missing=record["missing"], stubbed=record["stubbed"],
                 unproven_page_references=stats.get("unproven_kernel_page_references", 0),
                 segment_layout=stats.get("segment_layout")))
    require(len(objects) == 3, "Missing production object evidence")
    native = macho_info(tree / NATIVE)
    report = json.loads(output.with_suffix(".json").read_bytes())
    statistics = report["statistics"]
    receipts = list(output.parent.glob(".prelink-*/.sheng-evidence-*/receipt.json"))
    require(len(receipts) == 1, "Exactly one strict-prelink receipt is required")
    receipt = json.loads(receipts[0].read_bytes())
    require(receipt["status"] == "strict_candidate_written_runtime_unqualified" and receipt["candidate_written"]
            and receipt["native_data_placement"] == statistics["native_data_placement"] == "separate-native-data"
            and receipt["inputs"]["native_sha256"] == native["sha256"]
            and receipt["inputs"]["reference_sha256"] == digest(tree / REFERENCE)
            and receipt["candidate_sha256"] == digest(output)
            and report["runtime_qualified"] is False and report["loadable"] is False
            and not report["missing"] and not report["stubbed"]
            and not statistics.get("unproven_kernel_page_references", 0)
            and receipt["retained_entries_verified"] > 0 and statistics["corecrypto_hmac_sha256"],
            "Strict candidate receipt or identities disagree")
    save("strict-result.json", dict(status=receipt["status"], inputs=receipt["inputs"],
         candidate_sha256=receipt["candidate_sha256"], map_sha256=digest(output.with_suffix(".map.json")),
         placement=receipt["native_data_placement"], retained_entries=receipt["retained_entries_verified"],
         corecrypto_hmac_sha256=statistics["corecrypto_hmac_sha256"], runtime_qualified=False, loadable=False,
         candidate_bytes=output.stat().st_size, segment_layout=statistics["segment_layout"]))


if __name__ == "__main__":
    main()
