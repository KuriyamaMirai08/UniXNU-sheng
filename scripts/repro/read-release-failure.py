"""Preserve bounded layout replay inputs from a retained release archive.

Archived source is never executed, links are never followed, and large build
inputs/outputs remain in the original archive. This is an evidence reader.
"""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath


def selected(path):
    """Select exact replay inputs; never include runtime identity or key material."""
    parts = path.parts
    name = path.name
    if parts and parts[0] == "evidence":
        return True
    if parts and parts[0] == "baseline-evidence":
        return name in ("kernel.py", "native.macho")
    if str(path).startswith("UniXNU/kits/XnuPrelink/"):
        return path.suffix in (".py", ".json", ".md")
    if str(path) == "out/ipsw/24A446/kernelcache.decompressed":
        return True
    if str(path).startswith("out/sheng/ipados-27.0.1-24A446/sheng_ipados27/"):
        if name in ("mach.development.bcm2837.unstripped.noctf", "mach.release.bcm2837.unstripped.noctf", ".config"):
            return True
        if "logs" in parts and path.suffix in (".log", ".json", ".txt"):
            return True
        if "kernel" in parts and path.suffix in (".py", ".json", ".log"):
            return True
        if "fileset-reference" in parts and "source" not in parts and "lto-obj" not in parts:
            return name in ("native-stubs.c", "native-stubs.o", "lto-command.json", "source-sha256.json", "lto-build.log", "inputs.json", "omitted-unavailable-forced-exports.json")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with args.archive.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    entries, extracted = [], []
    with tarfile.open(args.archive, "r|gz") as archive:
        for entry in archive:
            path = PurePosixPath(entry.name)
            if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
                raise ValueError("Invalid archive path: " + entry.name)
            entries.append(dict(path=entry.name, bytes=entry.size, type=entry.type.decode("ascii")))
            if not entry.isfile() or not selected(path):
                continue
            if sum(row["bytes"] for row in extracted) + entry.size > 1024**3:
                raise ValueError("Selected replay inputs exceed 1 GiB")
            destination = output.joinpath(*path.parts).resolve()
            if not destination.is_relative_to(output) or destination.exists():
                raise ValueError("Duplicate or escaped destination: " + entry.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest, count = hashlib.sha256(), 0
            with archive.extractfile(entry) as source, destination.open("xb") as target:
                while blob := source.read(1024 * 1024):
                    target.write(blob)
                    digest.update(blob)
                    count += len(blob)
            if count != entry.size:
                raise ValueError("Truncated file: " + entry.name)
            extracted.append(dict(path=entry.name, bytes=count, sha256=digest.hexdigest()))
            print("Retained:", entry.name, count, flush=True)
    receipt = dict(archive=str(args.archive.resolve()), archive_sha256=archive_hash,
                   archive_bytes=args.archive.stat().st_size, entries=entries,
                   extracted=extracted, links_followed=False, archive_code_executed=False,
                   device_operations=False)
    (output / "EXTRACTION.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(archive_sha256=archive_hash, files=len(extracted),
                          extracted_bytes=sum(row["bytes"] for row in extracted))))


if __name__ == "__main__":
    main()
