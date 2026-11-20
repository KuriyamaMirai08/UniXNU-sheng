#!/usr/bin/env python3
"""Install digest-addressed ARM64 Tahoe bottles in the hosted runner keg paths."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
from urllib.request import Request, urlopen

VERSION = "23.1.4"
PREFIX = Path("/opt/homebrew")
BOTTLES = {
    # Z3 5.3.3 is the arm64_tahoe bottle from Homebrew/core at 768a1d39b034.
    # LLVM 23.1.4 loads libz3.5.3.dylib through the Homebrew opt path.
    "z3": ("5.3.3", "db365f6d26cd7c5523e0ce18ac6472fb10915f78884c22f797ecaced4413a73e", {
        "lib/libz3.5.3.3.0.dylib": "dc6ad4d2d1714859b927fc49082041a9a50976069ef3ce274dba03813cbaacb1",
    }),
    "llvm": (VERSION, "a5c46d2e124d1df2edae4a0f304a0af28f2bad257b6077c18cf93987048fb45f", {
        "bin/clang-23": "5c51770b83a5407e507ad19fcfe1ec141deeb15f0d86312568915f3637f31f5a",
        "bin/llvm-objcopy": "7e4393e6ba3d38d3c057e554404b1faec148249ef9ae1daf4c9e1c6e06f1e52d",
        "bin/llvm-nm": "112f093d81d2b827eac76fd79cb4845e459378f5058d820f3fcaf921813ef470",
        "bin/llvm-ar": "aa6beb9ec36a604bda581a547a8915d0a669ca410b9311d4b802781f66218840",
    }),
    "lld": (VERSION, "f2da69e86f04075ab83199af9d00a15297116f9649f63960bc36e179ba79a38c", {
        "bin/lld": "e2e27a717d37e0892342d07760eb95c2683b9347619144472ddb3e6e4a8d8d9d",
    }),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(name, sha256, path):
    token_url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:homebrew/core/{name}:pull"
    with urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    request = Request(f"https://ghcr.io/v2/homebrew/core/{name}/blobs/sha256:{sha256}",
                      headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=60) as response, path.open("xb") as target:
        shutil.copyfileobj(response, target, 1024 * 1024)
    if digest(path) != sha256:
        raise ValueError(f"{name} bottle failed SHA-256 verification")


def main():
    runner_temp, evidence = (Path(arg) for arg in sys.argv[1:])
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise ValueError("Expected macOS ARM64")
    runner_temp.mkdir()
    evidence.parent.mkdir(exist_ok=True)
    records = {}
    brew_env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_UPGRADE="1",
                    HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1", HOMEBREW_NO_INSTALL_CLEANUP="1")
    for name, (bottle_version, bottle_sha, binary_pins) in BOTTLES.items():
        archive = runner_temp / f"{name}--{bottle_version}.arm64_tahoe.bottle.tar.gz"
        fetch(name, bottle_sha, archive)
        keg = PREFIX / "Cellar" / name / bottle_version
        opt = PREFIX / "opt" / name
        if keg.exists() or (opt.exists() and not opt.is_symlink()):
            raise ValueError(f"Unexpected existing keg or opt directory for {name}")
        with tarfile.open(archive) as source:
            for binary, expected in binary_pins.items():
                member = source.getmember(f"{name}/{bottle_version}/{binary}")
                if not member.isfile():
                    raise ValueError(f"Expected regular bottle member {member.name}")
                with source.extractfile(member) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise ValueError(f"{binary} differs from the reviewed bottle bytes")
        # Pour the pinned Z3 before LLVM. The workflow supplies the other
        # dependencies. Disable dependency resolution for each local bottle.
        subprocess.run([PREFIX / "bin/brew", "install", "--formula", "--ignore-dependencies", archive],
                       env=brew_env, check=True)
        if opt.resolve(strict=True) != keg.resolve(strict=True):
            raise ValueError(f"{name} did not select the pinned keg")
        records[name] = dict(bottle_version=bottle_version, bottle_sha256=bottle_sha,
                             packaged_binary_sha256=binary_pins)
        archive.unlink()
    z3_library = PREFIX / "opt/z3/lib/libz3.5.3.dylib"
    z3_target = PREFIX / "Cellar/z3" / BOTTLES["z3"][0] / "lib/libz3.5.3.3.0.dylib"
    if not z3_library.is_file() or z3_library.resolve(strict=True) != z3_target.resolve(strict=True):
        raise ValueError(f"LLVM requires {z3_library} from the pinned Z3 keg")
    expected_dependencies = [z3_library, PREFIX / "opt/zstd/lib/libzstd.1.dylib"]
    library = PREFIX / "opt/llvm/lib/libLLVM.23.1.dylib"
    linkage = subprocess.check_output(["otool", "-L", library], text=True)
    load_paths = {line.split(" (compatibility version ", 1)[0].strip()
                  for line in linkage.splitlines()[1:]}
    for path in expected_dependencies:
        if str(path) not in load_paths or not path.is_file():
            raise ValueError(f"LLVM runtime dependency missing from load commands or disk: {path}")
    if "@@HOMEBREW_" in linkage:
        raise ValueError("Homebrew did not resolve LLVM runtime paths")
    records["llvm"]["libLLVM_sha256"] = digest(library)
    records["llvm"]["runtime_dependency_sha256"] = {str(path): digest(path) for path in expected_dependencies}

    for name, paths in {"llvm": ("clang", "llvm-objcopy", "llvm-nm", "llvm-ar"),
                        "lld": ("ld64.lld", "ld.lld")}.items():
        records[name]["versions"] = {}
        for program in paths:
            executable = PREFIX / "opt" / name / "bin" / program
            version = subprocess.check_output([executable, "--version"], text=True).strip()
            if not any(VERSION == word for word in version.split()):
                raise ValueError(f"Unexpected {program} version")
            records[name]["versions"][program] = dict(version=version, sha256=digest(executable))
    evidence.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
