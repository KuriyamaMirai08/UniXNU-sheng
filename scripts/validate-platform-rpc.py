#!/usr/bin/env python3
"""Generate one platform RPC IDL and compile three retained XNU units.

Use only an isolated copy of the successful clean tree. Keep original bytes,
diffs, commands and errors. No kernel/prelink/payload/device builder is run.
A successful object compilation remains separate from wire and boot review.
"""
import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ARCHIVE_SHA = "76f8549e40c2657ec71149b82b83c696d3ccfeefcc00d8742e409cad67d5a01b"
CLANG_SHA = "d2e4bf622758eee1bf7267c060497fb2c41e098d37b0fca8be73898dc7e14eda"
OLD_ROOT = "/Users/runner/work/_temp/unixnu-repro/43615501493-1/current"
TREE_NAME = "out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree"
SELECTED = tuple(TREE_NAME + "/" + p for p in (
    ".cache/xnu-work/", ".cache/fakeroot/", "build/xnu/ios-obj/"))
RPC_SYMBOLS = (
    "__ZN9IOService20CallPlatformFunctionEP8OSStringbP12OSDictionaryPS3_PFiP15OSMetaClassBase5IORPCE",
    "__ZN9IOService25CallPlatformFunction_ImplEP8OSStringbP12OSDictionaryPS3_",
    "__ZN9IOService27CallPlatformFunction_InvokeE5IORPCP15OSMetaClassBasePFiS2_P8OSStringbP12OSDictionaryPS6_E",
)
RPC_ID = 0xBF66F4287C60EF85
SOURCE_SHA = {
    "iokit/DriverKit/IOService.iig": "874c48d99a6663f339a21479d05fd39d2fdca0f6fdf0c1515d8d71391826363a",
    "iokit/Kernel/IOService.cpp": "eb88d26393116579f86932497fe99961db55ed095a5e33457d9c166392bc9154",
    "iokit/Kernel/IOUserServer.cpp": "762d6dfb51fca17e90d08cd317a3a0cab7b9fde7cc83da5d95068c297a019256",
    "iokit/IOKit/IOKitKeysPrivate.h": "9ab32cbe172fef8227f1dbd49abaf7bab43c50d8be2edfec109505bcd95a1711",
    "config/IOKit.exports": "a2b4b40b7559a37ccb0d29efb5972e30c9dda6a3e56eb57c9120c2a7a8eda76d",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run(command, cwd, evidence, label, required=True):
    write_json(evidence / (label + ".command.json"), dict(argv=list(map(str, command)), cwd=str(cwd)))
    with (evidence / (label + ".log")).open("wb") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    print(label, "returncode", result.returncode, flush=True)
    if required and result.returncode:
        raise RuntimeError(label + " failed; original diagnostics preserved")
    return result.returncode


def safe_extract(archive, destination, evidence):
    regular, links, modes, seen = [], [], [], set()
    with tarfile.open(archive, "r|gz") as source:
        for entry in source:
            name = entry.name.removeprefix("./")
            if not name.startswith(SELECTED):
                continue
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError("Invalid archive member")
            path = destination / name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Archive member outside experiment")
            if name in seen:
                raise ValueError("Duplicate selected archive member")
            seen.add(name)
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif entry.issym():
                target = entry.linkname
                if target.startswith(OLD_ROOT + "/"):
                    target = str(destination / target[len(OLD_ROOT) + 1:])
                elif target.startswith("/"):
                    raise ValueError("External archive link")
                if not (path.parent / target).resolve().is_relative_to(destination.resolve()):
                    raise ValueError("Archive link escaped experiment")
                links.append((path, target))
            elif entry.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as reader, path.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                modes.append((path, entry.mode))
                regular.append(dict(member=name, bytes=entry.size, sha256=sha(path)))
            else:
                raise ValueError("Unsupported selected archive type")
    for path, mode in modes:
        path.chmod(mode & 0o777)
    for path, target in links:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    write_json(evidence / "restored-inputs.json", regular)
    write_json(evidence / "restored-links.json", [dict(path=str(p.relative_to(destination)), target=t) for p, t in links])
    print("Restored:", len(regular), "regular files;", len(links), "links", flush=True)


def generate(iig, sdk, source, obj, destination, evidence, label):
    destination.mkdir()
    command = [iig, "--def", str(source / "iokit/DriverKit/IOService.iig"),
               "--header", str(destination / "IOService.h"),
               "--impl", str(destination / "IOService.iig.cpp"), "--framework-name", "DriverKit", "--"]
    for path in (source / "iokit", source / "osfmk", source / "bsd", obj / "bsd", source / "EXTERNAL_HEADERS"):
        command.append("-I" + str(path))
    command += ["-isysroot", sdk, "-x", "c++", "-std=gnu++2b", "-D__IIG=1",
                "-DDRIVERKIT_PRIVATE=1", "-DPRIVATE_WIFI_ONLY=1", "-DXNU_PLATFORM_iPhoneOS"]
    run(command, source, evidence, label)


def ids(header):
    return {name: int(value, 16) for name, value in re.findall(
        r"#define\s+(IOService_\w+_ID)\s+(0x[0-9a-fA-F]+)ULL", header)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    receipt = dict(status="started", updated_at=datetime.now(timezone.utc).isoformat(),
                   baseline_run=43615501493, full_kernel_build=False, prelink_invoked=False,
                   device_operations=False, source_archive_modified=False, candidate_kernel_written=False,
                   wire_qualified=False, backend_behavior_qualified=False, compiled_units=[])
    exitcode = 1
    try:
        work = args.work.resolve()
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        if work.exists() or not work.is_relative_to(runner_temp) or work == runner_temp:
            raise ValueError("Experiment must be a new directory under RUNNER_TEMP")
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise ValueError("Validation requires the retained Apple arm64 compiler environment")
        receipt["archive_sha256"] = sha(args.archive)
        if receipt["archive_sha256"] != ARCHIVE_SHA:
            raise ValueError("Successful-build archive identity changed")
        work.mkdir()
        safe_extract(args.archive, work, evidence)
        tree = work / TREE_NAME
        source = tree / ".cache/xnu-work"
        obj = tree / "build/xnu/ios-obj"
        generated = obj / "DEVELOPMENT_ARM64_BCM2837/iokit/DriverKit"
        cpo_dir = obj / "DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT"
        for name, expected in SOURCE_SHA.items():
            if sha(source / name) != expected:
                raise ValueError("Retained patch source identity changed: " + name)
        compiler = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True).strip()
        iig = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "iig"], text=True).strip()
        sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
        receipt.update(compiler=compiler, compiler_sha256=sha(Path(compiler)), iig=iig,
                       iig_sha256=sha(Path(iig)), sdk=sdk, runner_arch=platform.machine())
        if receipt["compiler_sha256"] != CLANG_SHA:
            raise ValueError("Apple compiler differs from successful clean build")
        run([compiler, "--version"], repo, evidence, "compiler-version")
        before = evidence / "before"
        before.mkdir()
        for name in SOURCE_SHA:
            target = before / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        baseline_generated = evidence / "baseline-generated"
        generate(iig, sdk, source, obj, baseline_generated, evidence, "iig-baseline")
        equal = {}
        for name in ("IOService.h", "IOService.iig.cpp"):
            a, b = (generated / name).read_bytes(), (baseline_generated / name).read_bytes()
            equal[name] = a == b
            if a != b:
                difference = difflib.unified_diff(a.decode().splitlines(keepends=True), b.decode().splitlines(keepends=True),
                                                  fromfile="retained/" + name, tofile="regenerated/" + name)
                (evidence / ("baseline-" + name + ".diff")).write_text("".join(difference))
        receipt["baseline_generator_bytes_equal"] = equal
        if not all(equal.values()):
            raise ValueError("Same-source IDL regeneration differs from retained output")
        patch = repo / "patches/xnu-12377/driverkit-platform-function.patch"
        shutil.copyfile(patch, evidence / "implementation.patch")
        receipt["patch_sha256"] = sha(patch)
        run(["git", "apply", "--check", str(patch)], source, evidence, "patch-check")
        run(["git", "apply", str(patch)], source, evidence, "patch-apply")
        after = evidence / "after"
        after.mkdir()
        for name in SOURCE_SHA:
            target = after / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        current_generated = evidence / "generated"
        generate(iig, sdk, source, obj, current_generated, evidence, "iig-patched")
        old_ids = ids((baseline_generated / "IOService.h").read_text())
        new_ids = ids((current_generated / "IOService.h").read_text())
        receipt["existing_method_ids_unchanged"] = all(new_ids.get(k) == v for k, v in old_ids.items())
        receipt["generated_rpc_id"] = hex(new_ids.get("IOService_CallPlatformFunction_ID", 0))
        receipt["generated_rpc_id_matches"] = new_ids.get("IOService_CallPlatformFunction_ID") == RPC_ID
        for name in ("IOService.h", "IOService.iig.cpp"):
            a, b = (baseline_generated / name).read_text(), (current_generated / name).read_text()
            (evidence / (name + ".diff")).write_text("".join(difflib.unified_diff(
                a.splitlines(keepends=True), b.splitlines(keepends=True), fromfile="before/" + name, tofile="after/" + name)))
        for name in ("IOService.h", "IOService.iig.cpp"):
            for target in obj.rglob(name):
                if not target.resolve().is_relative_to(work):
                    raise ValueError("Generated-header link escaped experiment")
                shutil.copyfile(current_generated / name, target)
        for target in (tree / ".cache/fakeroot").rglob("IOService.h"):
            if "/DriverKit/" in str(target) or "/DriverKit.framework/" in str(target):
                shutil.copyfile(current_generated / "IOService.h", target)
        objects = evidence / "objects"
        objects.mkdir()
        commands, codes = [], []
        for name in ("IOService", "IOUserServer", "IOService.iig"):
            fragment = cpo_dir / (name + ".cpo.json")
            text = fragment.read_text()
            command, end = json.JSONDecoder().raw_decode(text)
            if text[end:].strip() != ",":
                raise ValueError("Unexpected retained clang fragment trailer")
            argv = [value.replace(OLD_ROOT, str(work)) for value in command["arguments"]]
            if argv[0] != compiler:
                raise ValueError("Retained command selects a different compiler")
            output = objects / (name + ".cpo")
            argv[argv.index("-o") + 1] = str(output)
            cwd = Path(command["directory"].replace(OLD_ROOT, str(work)))
            commands.append(dict(fragment_sha256=sha(fragment), original=command,
                                 actual=dict(argv=argv, cwd=str(cwd))))
            code = run(argv, cwd, evidence, "compile-" + name, required=False)
            codes.append(code)
            if code == 0:
                receipt["compiled_units"].append(dict(name=name, sha256=sha(output), bytes=output.stat().st_size))
        write_json(evidence / "compile-commands.json", commands)
        receipt["compile_returncodes"] = codes
        if any(codes):
            raise RuntimeError("Targeted object compilation failed")
        run(["xcrun", "nm", "-g", *map(str, sorted(objects.glob("*.cpo")))], repo, evidence, "object-symbols")
        symbols = (evidence / "object-symbols.log").read_text()
        receipt["expected_rpc_definitions"] = {symbol: bool(re.search(r"\b[TDS]\s+" + re.escape(symbol) + r"$", symbols, re.M)) for symbol in RPC_SYMBOLS}
        receipt["partial_link_returncode"] = run([
            "xcrun", "ld", "-r", "-arch", "arm64e", "-o", str(objects / "rpc-iokit.o"),
            *map(str, sorted(objects.glob("*.cpo")))], repo, evidence, "partial-link", required=False)
        for unit in receipt["compiled_units"]:
            run(["xcrun", "otool", "-tvV", str(objects / (unit["name"] + ".cpo"))], repo, evidence,
                "disassembly-" + unit["name"], required=False)
        receipt["status"] = "objects_compiled_wire_and_behavior_review_pending"
        if not receipt["existing_method_ids_unchanged"] or not receipt["generated_rpc_id_matches"] or not all(receipt["expected_rpc_definitions"].values()):
            raise ValueError("Generated RPC ABI differs from retained interface")
        exitcode = 0
    except Exception as error:
        receipt.update(status="validation_failed", error_type=type(error).__name__, error=str(error))
        print(type(error).__name__ + ": " + str(error), flush=True)
    finally:
        receipt["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(evidence / "receipt.json", receipt)
        manifest = {p.relative_to(evidence).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
                    for p in sorted(evidence.rglob("*")) if p.is_file() and p.name != "SHA256.json"}
        write_json(evidence / "SHA256.json", manifest)
    return exitcode


if __name__ == "__main__":
    raise SystemExit(main())
