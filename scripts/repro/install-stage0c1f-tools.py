#!/usr/bin/env python3
"""Install digest-addressed ARM64 Tahoe bottles in the hosted runner keg paths."""
import hashlib
import json
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
    "llvm": ("a5c46d2e124d1df2edae4a0f304a0af28f2bad257b6077c18cf93987048fb45f", {
        "clang-23": "5c51770b83a5407e507ad19fcfe1ec141deeb15f0d86312568915f3637f31f5a",
        "llvm-objcopy": "7e4393e6ba3d38d3c057e554404b1faec148249ef9ae1daf4c9e1c6e06f1e52d",
        "llvm-nm": "112f093d81d2b827eac76fd79cb4845e459378f5058d820f3fcaf921813ef470",
        "llvm-ar": "aa6beb9ec36a604bda581a547a8915d0a669ca410b9311d4b802781f66218840",
    }),
    "lld": ("f2da69e86f04075ab83199af9d00a15297116f9649f63960bc36e179ba79a38c", {
        "lld": "e2e27a717d37e0892342d07760eb95c2683b9347619144472ddb3e6e4a8d8d9d",
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
    for name, (bottle_sha, binary_pins) in BOTTLES.items():
        archive = runner_temp / f"{name}.tar.gz"
        fetch(name, bottle_sha, archive)
        keg = PREFIX / "Cellar" / name / VERSION
        opt = PREFIX / "opt" / name
        if keg.exists() or (opt.exists() and not opt.is_symlink()):
            raise ValueError(f"Unexpected existing keg or opt directory for {name}")
        # git and native build recipes use /opt/homebrew/opt/<name> regardless of PATH.
        with tarfile.open(archive) as source:
            source.extractall(PREFIX / "Cellar", filter="tar")
        for binary, expected in binary_pins.items():
            if digest(keg / "bin" / binary) != expected:
                raise ValueError(f"{binary} differs from the reviewed bottle bytes")
        link = opt.with_name(f".{name}-stage0c1f")
        link.symlink_to(keg, target_is_directory=True)
        link.replace(opt)
        records[name] = dict(bottle_sha256=bottle_sha, binary_sha256=binary_pins)
        archive.unlink()
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
