#!/usr/bin/env python3
"""One clean source candidate through the author's release and boot packer.

Only this isolated checkout is changed. Exact source transformations and
baseline evidence are recorded; no device or stable output is accessed.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import threading
import time
from pathlib import Path

from preserve import apply

FRAMEWORK = "97437dcf7389484a0eeaa8067725ce743aff18ef"
UEFI = "66421cb7bb5694843aec8de1ca3d1de4c20cca38"
ARCHIVE_SHA = "76f8549e40c2657ec71149b82b83c696d3ccfeefcc00d8742e409cad67d5a01b"
SOURCE_HELPER_SHA = "e3ca14afe6c14b0745385da7399c4380a90be2237ad331bf64156dde29ddcc73"


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-archive", type=Path, required=True)
    args = parser.parse_args()
    require_host = platform.system() == "Darwin" and platform.machine() == "arm64"
    if not require_host:
        raise ValueError("Clean release requires the reviewed Apple arm64 host")
    root = Path(os.environ["RUNNER_TEMP"]) / "unixnu-candidate" / (os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]) / "current"
    root.mkdir(parents=True, exist_ok=False)
    evidence = root / "evidence"
    evidence.mkdir()
    with open(os.environ["GITHUB_ENV"], "a") as stream:
        stream.write("CANDIDATE_ATTEMPT=" + str(root) + "\n")
    deadline = time.monotonic() + 300 * 60
    stages = []
    os.environ.update(PYTHONUNBUFFERED="1", RUSTUP_TOOLCHAIN="1.98.0",
                      UNIXNU_SHENG_BOOT_CANDIDATE="1", UNIXNU_SHENG_AUTHOR_AUDIT="1", ZERO_AR_DATE="1")

    def save(name, value):
        (evidence / name).write_text(json.dumps(value, indent=2) + "\n")

    def step(name, argv, cwd=root):
        row = dict(stage=name, argv=list(map(str, argv)), cwd=str(cwd), start=time.time(), status="running")
        stages.append(row)
        save("stages.json", stages)
        print("CANDIDATE stage:", name, flush=True)
        try:
            with (evidence / (name + ".log")).open("wb") as log:
                process = subprocess.Popen(list(map(str, argv)), cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                stop = threading.Event()
                def progress():
                    while not stop.wait(30):
                        print("CANDIDATE running:", name, "log_bytes=" + str((evidence / (name + ".log")).stat().st_size), flush=True)
                thread = threading.Thread(target=progress, daemon=True)
                thread.start()
                try:
                    code = process.wait(timeout=max(1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    row["timeout"] = True
                    raise RuntimeError("Candidate reached the 300-minute execution budget")
                finally:
                    stop.set()
                    thread.join()
            row.update(returncode=code, status="passed" if code == 0 else "failed")
            if code:
                raise RuntimeError("First failed stage: " + name)
        except BaseException:
            row["status"] = "failed"
            raise
        finally:
            row["end"] = time.time()
            save("stages.json", stages)
            print("CANDIDATE ended:", name, row["status"], flush=True)

    try:
        source_sha = os.environ["GITHUB_SHA"]
        save("source-pins.json", dict(device=source_sha, framework=FRAMEWORK, uefi=UEFI,
                                     fresh_source_build=True, object_cache_restored=False, device_operations=False))
        step("environment", ["bash", "-c", "sw_vers; uname -a; sysctl hw.memsize hw.ncpu; df -k; xcodebuild -version; xcrun clang --version; brew list --versions; rustc +1.98.0 --version"])
        if shutil.disk_usage(root).free < 12 * 1024**3:
            raise ValueError("Less than 12 GiB free before source fetch")
        for name in list(os.environ):
            if name.startswith(("CCACHE_", "SCCACHE_")) or name in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS", "BASH_ENV"):
                os.environ.pop(name, None)
        for name in ("TMPDIR", "XDG_CACHE_HOME", "CLANG_MODULE_CACHE_PATH", "CARGO_TARGET_DIR"):
            path = root / "caches" / name
            path.mkdir(parents=True)
            os.environ[name] = str(path)
        compiler = Path(subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True).strip())
        if file_hash(compiler) != "d2e4bf622758eee1bf7267c060497fb2c41e098d37b0fca8be73898dc7e14eda":
            raise ValueError("Apple compiler differs from qualified candidate object checks")
        save("toolchain.json", dict(compiler=str(compiler), sha256=file_hash(compiler),
                                    image_version=os.environ.get("ImageVersion")))
        baseline = root / "baseline-evidence"
        baseline.mkdir()
        if file_hash(args.baseline_archive) not in (ARCHIVE_SHA, "f9328464d2f664a2b526a0d91bd3f35659cdfd9e2f26a5fa7696cf5f40c442ba"):
            raise ValueError("Retained clean archive identity changed")
        bootstrap_contract = json.loads((Path(__file__).parents[1] / "clean-prelink-contract.json").read_text())
        with tarfile.open(args.baseline_archive, "r|gz") as source:
            for entry in source:
                if not entry.isfile():
                    continue
                if not (entry.name.removeprefix("./") in ("baseline-evidence/native.macho", "baseline-evidence/kernel.py") or entry.name.endswith("/mach.development.bcm2837.unstripped.noctf") or entry.name.endswith("/scripts/unixnu/kernel.py")):
                    continue
                data = source.extractfile(entry).read()
                digest = hashlib.sha256(data).hexdigest()
                if digest == bootstrap_contract["inputs"]["native"]:
                    (baseline / "native.macho").write_bytes(data)
                if digest == bootstrap_contract["regression_source_sha256"]:
                    (baseline / "kernel.py").write_bytes(data)
        for name in ("native.macho", "kernel.py"):
            if not (baseline / name).is_file():
                raise ValueError("Missing exact baseline evidence " + name)
        os.environ["UNIXNU_SHENG_BASELINE_NATIVE"] = str(baseline / "native.macho")
        os.environ["UNIXNU_SHENG_REGRESSION_SOURCE"] = str(baseline / "kernel.py")
        for name, repository, revision in (("device", "KuriyamaMirai08/UniXNU-sheng", source_sha),
                                           ("UniXNU", "UniXNU/UniXNU", FRAMEWORK),
                                           ("uefi-sheng", "UniXNU/uefi-sheng", UEFI)):
            destination = root / name
            step("init-" + name, ["git", "init", destination])
            step("fetch-" + name, ["git", "-C", destination, "fetch", "--depth", "1", "https://github.com/" + repository + ".git", revision])
            step("checkout-" + name, ["git", "-C", destination, "checkout", "--detach", revision])
            if name != "uefi-sheng":
                step("submodules-" + name, ["git", "-C", destination, "submodule", "update", "--init", "--recursive"])
            if subprocess.check_output(["git", "-C", destination, "rev-parse", "HEAD"], text=True).strip() != revision:
                raise ValueError("Source revision changed: " + name)
            if any(destination.rglob("local.toml")):
                raise ValueError("Undeclared source override: " + name)
        device, framework, uefi = root / "device", root / "UniXNU", root / "uefi-sheng"
        os.environ.update(UNIXNU_ROOT=str(framework), UNIXNU_DEVICE=str(device), UNIXNU_UEFI=str(uefi))
        if file_hash(framework / "scripts/build-sheng-source-drivers.py") != SOURCE_HELPER_SHA:
            raise ValueError("Source-driver helper is not the qualified author input")
        step("compatibility", ["python3", "scripts/prepare-package-ci.py", "--unixnu", framework], device)
        apply(framework, evidence)
        patch = device / "patches/build/sheng-reference-archive.patch"
        step("reference-patch-check", ["git", "apply", "--check", patch], framework)
        step("reference-patch", ["git", "apply", patch], framework)
        step("optional-provider-source-guards", ["python3", "scripts/prepare-sheng-author-audit.py", "--unixnu", framework,
                                               "--evidence", evidence], device)
        step("framework-diff", ["git", "diff", "--binary"], framework)
        step("reference-builder-regressions", ["python3", "scripts/test-fileset-reference.py", "-v"], framework)
        (root / "build.toml").write_text("[build]\n")
        common = ["--os", "27", "--out", root / "out", "--config", root / "build.toml", "--uefi", uefi, "-j", "3"]
        step("dependencies", ["python3", framework / "unixnu", "fetch", "-D", device, *common])
        step("configuration", ["bash", "scripts/package.sh", *common, "--no-deps", "--check"], device)
        step("source-status", ["python3", framework / "unixnu", "status", "-D", device, *common, "--json"])
        step("assemble-tree", ["python3", framework / "unixnu", "tree", "-D", device, *common])
        tree = root / "out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree"
        old = [str(p) for p in tree.rglob("*") if p.is_file() and (p.suffix in (".o", ".a", ".cpo") or p.name == "kernel.macho")]
        save("precompile-objects.json", old)
        if old:
            raise ValueError("Precompiled build objects exist in the fresh tree")
        kit = tree / "kits/XnuPrelink"
        step("author-prelink-regressions", ["python3", "-m", "unittest", "test_fileset_emit", "test_fileset_layout", "test_fileset_match", "test_fileset_shape"], kit)
        step("optional-provider-link-checks", ["python3", "scripts/check-sheng-optional-providers.py", "--tree", tree,
                                              "--output", evidence / "optional-link"], device)
        # Fetch KernelCache before archive recipes, whose new PAL adapter needs
        # those exact bytes. Source build outputs remain empty at this point.
        step("kernelcache", ["python3", framework / "unixnu", "ipsw", "fetch", "KernelCache", "-D", device, *common])
        cache = root / "out/ipsw/24A446/kernelcache.decompressed"
        os.environ["UNIXNU_KERNELCACHE"] = str(cache)
        for name, command in (("touch-firmware", ["python3", "scripts/extract-files.py"]),
                              ("ath12k", ["bash", "drivers/Ath12kWifi/tools/fetch-sources.sh"]),
                              ("bluetooth-source", ["python3", "drivers/QcaBluetooth/tools/prepare-linux.py"]),
                              ("bluetooth-firmware", ["python3", "scripts/stage-bluetooth-firmware.py", ".cache/bt-stage", "--fetch"]),
                              ("stock-firmware", ["python3", "scripts/download-sheng-firmware.py", "--connections", "16"]),
                              ("extract-stock-firmware", ["python3", "scripts/extract-sheng-firmware.py", "--delete-archive"]),
                              ("import-uefi", ["python3", "scripts/import-sheng-uefi.py"])):
            step(name, command, device)
        seed = Path(os.environ["SHENG_CANDIDATE_DATA"])
        contract = json.loads((device / "scripts/sheng-candidate-input-contract.json").read_text())
        if file_hash(seed) != contract["seed_sha256"]:
            raise ValueError("Installed seed changed before release")
        step("release", ["bash", "scripts/package.sh", *common, "--no-deps", "--data-ramdisk", seed], device)
        provider_plan = tree / "build/sheng-optional-providers/provider-plan.json"
        if not provider_plan.is_file():
            raise ValueError("Actual optional-provider build receipt is missing")
        import sys
        sys.path.insert(0, str(tree / "kits/XnuPrelink"))
        from kc_image import Image
        native_path = tree / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf"
        native_data = native_path.read_bytes()
        native = Image(native_data)
        names = {name for aliases in native.symbols().values() for name in aliases}
        absent = json.loads(provider_plan.read_text())["absent_functions"]
        if any(name in names for name in absent):
            raise ValueError("An absent optional interface acquired a synthesized definition")
        native.fixups()  # Preserve the author's rejection of imports and binds.
        if list((tree / "build/xnu/fileset-reference").rglob("native-stubs.c")):
            raise ValueError("The reference kernel contains synthesized placeholders")
        save("optional-final-native.json", dict(absent_functions=absent, all_absent=True,
                                               chained_fixups_accepted=True, native_sha256=file_hash(native_path)))
        manifest = root / "out/sheng/ipados-27.0.1-24A446/sheng_ipados27/package.manifest.json"
        result = json.loads(manifest.read_text())
        if result["runtime"]["data_volume_uuid"] != contract["seed_uuid"]:
            raise ValueError("Final runtime UUID differs from the actual installation")
        save("package.manifest.json", result)
        save("result.json", dict(status="author_release_built_static_review_pending", full_source_build=True,
                                 device_operations=False, stable_outputs_modified=False, outputs=result["outputs"]))
    finally:
        inventory = []
        for base, directories, filenames in os.walk(root):
            directories[:] = [name for name in directories if name not in (".git", "__pycache__")]
            for name in filenames:
                path = Path(base) / name
                if path.name == ".git":
                    continue
                if path.is_symlink():
                    inventory.append(dict(path=str(path.relative_to(root)), link=os.readlink(path)))
                elif path.is_file():
                    inventory.append(dict(path=str(path.relative_to(root)), bytes=path.stat().st_size, sha256=file_hash(path)))
        save("file-inventory.json", inventory)


if __name__ == "__main__":
    main()
