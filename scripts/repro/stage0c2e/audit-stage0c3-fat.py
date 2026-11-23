#!/usr/bin/env python3
"""Package one in-run candidate with the approved 48 GiB APFS seed, read back FAT, and run 2C audits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import tomllib

TRACK = "stage0c3-production"
BLOCK = 4096
SEED_LOGICAL = 48 << 30
EXPECTED_SEED_SHA = "9c7d8c86fb56aa6dd2d9a65b0345a8b580a4cb0b391e9b8265db0197b9fcffea"
EXPECTED_SEED_BYTES = 1183872
EXPECTED_CONTAINER_ID = "f64b5730fc854831905eae28cbc348f7"
EXPECTED_POLICY_SHA = "e0787c6c86441714f090642594c97dee5b8bfb472278823bcde1cfa9a8a3b46b"
MENU = "EFI/UniXNU/unixnu.toml"
PAYLOADS = "EFI/UniXNU/Payloads/"
KERNEL = PAYLOADS + "kernel.macho"
DATA = PAYLOADS + "scratch-data.img"
ROOT = KERNEL + ".vroot"
ADT = KERNEL + ".adt"
PATHS = {MENU, KERNEL, DATA, ROOT, ADT}
HEX = re.compile(r"[0-9a-f]{64}")
WINDOW = 0x130000000


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path: Path) -> dict:
    return dict(bytes=path.stat().st_size, sha256=digest(path))


def packed_pages(blob: bytes):
    need(32 <= len(blob) <= 256 << 20, "packed size")
    magic, version, block, logical, count = struct.unpack_from("<8sIIQQ", blob)
    need((magic, version, block) == (b"DBRDISK1", 1, BLOCK) and logical == SEED_LOGICAL
         and 0 < count <= min(65536, (len(blob) - 32) // 16), "packed header")
    cursor, past = 32 + count * 16, 0
    pages = {}
    for off, size in struct.iter_unpack("<QQ", blob[32:cursor]):
        need(size > 0 and (off | size) % BLOCK == 0 and past <= off <= off + size <= logical
             and cursor + size <= len(blob), "invalid packed extent")
        for delta in range(0, size, BLOCK):
            at = cursor + delta
            pages[(off + delta) // BLOCK] = blob[at:at + BLOCK]
        cursor += size
        past = off + size
    need(cursor == len(blob), "trailing packed data")
    return logical, pages


def valid_object(block, kind):
    if block is None or len(block) != BLOCK or (struct.unpack_from("<I", block, 24)[0] & 0xFFFF) != kind:
        return False
    low = high = 0
    for word, in struct.iter_unpack("<I", block[8:]):
        low += word
        high += low
    modulus = 0xFFFFFFFF
    a = modulus - (low + high) % modulus
    b = modulus - (low + a) % modulus
    return (a, b) == struct.unpack_from("<II", block)


def space_manager(logical: int, pages: dict):
    def nx_valid(block):
        return (valid_object(block, 1) and block[32:36] == b"NXSB"
                and struct.unpack_from("<IQ", block, 36) == (BLOCK, logical // BLOCK))

    start = pages.get(0)
    need(nx_valid(start), "invalid container superblock")
    desc_count, data_count, desc_base, data_base = struct.unpack_from("<IIqq", start, 104)
    need(0 < desc_count < 1 << 31 and 0 < data_count < 1 << 31
         and 0 < desc_base <= logical // BLOCK - desc_count and 0 < data_base <= logical // BLOCK - data_count,
         "unsupported or invalid checkpoint geometry")
    candidates = [(struct.unpack_from("<Q", p, 16)[0], lba, p) for lba, p in pages.items()
                  if desc_base <= lba < desc_base + desc_count and nx_valid(p)]
    need(bool(candidates), "no valid checkpoint superblock")
    xid, lba, checkpoint = max(candidates)
    need(checkpoint[72:88] == start[72:88] and checkpoint[104:128] == start[104:128], "checkpoint identity")
    index, length, data_index, data_length, space_oid = struct.unpack_from("<IIIIQ", checkpoint, 136)
    need(0 <= index < desc_count and 2 <= length <= desc_count and 0 <= data_index < data_count
         and 0 < data_length <= data_count and desc_base + (index + length - 1) % desc_count == lba,
         "checkpoint indices")
    matches = []
    for delta in range(length - 1):
        mapping = pages.get(desc_base + (index + delta) % desc_count)
        need(valid_object(mapping, 12) and struct.unpack_from("<Q", mapping, 16)[0] == xid, "invalid checkpoint map")
        flags, count = struct.unpack_from("<II", mapping, 32)
        need(flags == int(delta == length - 2) and 40 + count * 40 <= BLOCK, "invalid checkpoint map bounds")
        for dtype, _, size, _, fs, oid, address in struct.iter_unpack("<IIIIQQQ", mapping[40:40 + 40 * count]):
            if dtype & 0xFFFF == 5 and oid == space_oid and fs == 0:
                need(size == BLOCK and data_base <= address < data_base + data_count and address in pages,
                     "missing checkpoint space manager")
                matches.append(pages[address])
    need(len(matches) == 1 and valid_object(matches[0], 5)
         and struct.unpack_from("<QQ", matches[0], 8) == (space_oid, xid)
         and struct.unpack_from("<I", matches[0], 32)[0] == BLOCK, "invalid space manager")
    total, free, tier2 = (struct.unpack_from("<Q", matches[0], off)[0] for off in (48, 72, 96))
    need(total == logical // BLOCK and free <= total and tier2 == 0, "space manager bounds")
    return dict(
        container_id=start[72:88].hex(),
        allocated_bytes=(total - free) * BLOCK,
    )


def admit_production_seed(seed_bytes: bytes, approval_sha256: str, policy_sha256: str) -> dict:
    seed_sha = hashlib.sha256(seed_bytes).hexdigest()
    need(seed_sha == EXPECTED_SEED_SHA and len(seed_bytes) == EXPECTED_SEED_BYTES, "production seed byte identity")
    need(policy_sha256 == EXPECTED_POLICY_SHA, "root policy bundle identity")
    logical, pages = packed_pages(seed_bytes)
    stats = space_manager(logical, pages)
    need(stats["container_id"] == EXPECTED_CONTAINER_ID, "APFS container identity")
    approval = {
        "purpose": "resume-existing-only",
        "packed_sha256": seed_sha,
        "logical_bytes": logical,
        "apfs_container_id": stats["container_id"],
        "root_policy_bundle_sha256": policy_sha256,
    }
    app_bytes = (json.dumps(approval, indent=2) + "\n").encode("utf-8")
    need(hashlib.sha256(app_bytes).hexdigest() == approval_sha256, "seed approval SHA-256 mismatch")
    return {
        "logical_bytes": logical,
        "packed_bytes": len(seed_bytes),
        "packed_sha256": seed_sha,
        "allocated_bytes": stats["allocated_bytes"],
        "apfs_container_id": stats["container_id"],
        "approval_scope": "resume-existing-only",
        "approval_sha256": approval_sha256,
        "root_policy_bundle_sha256": policy_sha256,
        "static_seed_admission": "PASS",
        "initialization_allowed": False,
        "live_media_ownership": "NOT_OBSERVED",
        "device": "NO-GO",
    }


def menu_matches(data: bytes, command_line: str):
    menu = tomllib.loads(data.decode())
    need(menu.get("version") == 1 and menu.get("boot", {}).get("default") == "xnu"
         and menu.get("kits") == {"autoload": False} and "driver" not in menu,
         "FAT menu boot contract")
    boot, recovery, reset, shutdown = menu["entry"]
    need([(row["id"], row["type"]) for row in menu["entry"]]
         == [("xnu", "xnu"), ("recovery", "xnu"), ("reset", "action"), ("shutdown", "action")]
         and reset["action"] == "reset" and shutdown["action"] == "shutdown", "FAT menu roles")
    for row in (boot, recovery):
        need(row["path"] == "Payloads/kernel.macho" and row["initrd"] == "Payloads/scratch-data.img"
             and all(not key.startswith("confirm") for key in row), "FAT menu paths")
    expected_recovery = [arg for arg in command_line.split() if arg.split("=", 1)[0] not in {"data-persist", "log"}]
    need(boot["args"] == command_line and recovery["args"] == " ".join([*expected_recovery, "data-persist=1", "log=0"])
         and boot["args"].split().count("data-wal-v2=1") == 1
         and "data-reset=1" not in boot["args"] and "data-reset=2" not in boot["args"], "FAT menu arguments")


def check_adt(data: bytes):
    found = {}

    def visit(offset, parent, depth):
        need(depth < 32 and offset + 8 <= len(data), "FAT ADT node extent")
        prop_count, child_count = struct.unpack_from("<II", data, offset)
        offset += 8
        props = {}
        for _ in range(prop_count):
            need(offset + 36 <= len(data), "FAT ADT property header")
            key, size = struct.unpack_from("<32sI", data, offset)
            key = key.rstrip(b"\0")
            offset += 36
            end = offset + size
            need(key and key not in props and ((end + 3) & ~3) <= len(data), "FAT ADT property extent")
            props[key] = data[offset:end]
            offset = (end + 3) & ~3
        name = props.pop(b"name", b"")
        need(name.endswith(b"\0") and b"\0" not in name[:-1], "FAT ADT node name")
        path = parent + (name[:-1],) if depth else ()
        if path in {(b"chosen",), (b"chosen", b"memory-map")}:
            need(path not in found, "duplicate FAT ADT handoff node")
            found[path] = props
        for _ in range(child_count):
            offset = visit(offset, path, depth + 1)
        return offset

    need(visit(0, (), 0) == len(data), "FAT ADT trailing bytes")
    chosen = found[(b"chosen",)]
    need(chosen.get(b"darwinboot-memory-size") == struct.pack("<Q", WINDOW)
         and b"darwinboot-memory-excluded" not in chosen, "FAT ADT contiguous window")
    memory = found[(b"chosen", b"memory-map")]
    need(memory == {b"PackedRAMDisk": bytes(16), b"RootPolicies": bytes(16)}, "FAT ADT sidecar map")


def audit_directory(directory: Path, sealed: dict, policy: dict, pack_report: dict):
    files = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file()}
    need(set(files) == PATHS, "FAT file inventory")
    need(identity(files[KERNEL]) == sealed and identity(files[ROOT]) == policy, "FAT kernel or root policy changed")
    need(identity(files[DATA]) == {"bytes": EXPECTED_SEED_BYTES, "sha256": EXPECTED_SEED_SHA}, "FAT seed changed")
    need(digest(files[ADT]) == pack_report["adt_sha256"], "FAT ADT changed")
    check_adt(files[ADT].read_bytes())
    menu_matches(files[MENU].read_bytes(), pack_report["kernel_args"])
    return {name: identity(path) for name, path in sorted(files.items())}


def extract_volume(image: Path, directory: Path):
    directory.mkdir()
    subprocess.run(["mcopy", "-s", "-i", str(image.resolve()), "::/*", "."], cwd=directory,
                   env=dict(os.environ, MTOOLS_SKIP_CHECK="1", TZ="UTC"), capture_output=True, check=True)


def validate_receipt(row: dict, strict: dict, seal: dict):
    fields = {"track", "static_result", "production_inputs", "loadable", "runtime_qualified",
              "raw_kernel", "sealed_kernel", "map_sha256", "root_policy_source",
              "run_s_id", "seed_approval_sha256", "seed", "fat", "files",
              "darwinboot", "final_efi_map", "device"}
    need(set(row) == fields and row["track"] == TRACK and row["static_result"] == "PASS"
         and row["production_inputs"] is True and row["loadable"] is False
         and row["runtime_qualified"] is False
         and row["final_efi_map"] == "NOT_OBSERVED" and row["device"] == "NO-GO",
         "FAT receipt scope")
    need(row["raw_kernel"] == dict(bytes=strict["candidate_bytes"], sha256=strict["candidate_sha256"])
         and row["raw_kernel"]["sha256"] == seal["before_sha256"] and row["map_sha256"] == strict["map_sha256"]
         and row["sealed_kernel"] == dict(bytes=seal["bytes"], sha256=seal["after_sha256"])
         and row["darwinboot"] == "ACCEPT", "FAT receipt lineage")
    need(row["root_policy_source"] == "same-build-storage-report"
         and row["seed"] == dict(kind="production-48g-apfs", logical_bytes=SEED_LOGICAL,
                                 packed_bytes=EXPECTED_SEED_BYTES, sha256=EXPECTED_SEED_SHA),
         "FAT receipt input scope")
    files = row["files"]
    need(set(files) == PATHS and files[KERNEL] == row["sealed_kernel"]
         and files[DATA] == dict(bytes=EXPECTED_SEED_BYTES, sha256=EXPECTED_SEED_SHA), "FAT receipt inventory")
    for record in [row["fat"], *files.values()]:
        need(set(record) == {"bytes", "sha256"} and type(record["bytes"]) is int
             and 0 < record["bytes"] <= 2 << 30 and HEX.fullmatch(record["sha256"]), "FAT receipt identity")


def load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("temp", type=Path)
    cli.add_argument("pins", type=Path)
    cli.add_argument("--seed", type=Path, required=True)
    cli.add_argument("--approval-sha256", required=True)
    cli.add_argument("--run-s-id", required=True)
    cli.add_argument("--objdump", default=None)
    args = cli.parse_args()

    temp = args.temp.resolve()
    private = temp / "stage0c1f-private"
    evidence = temp / "stage0c1f-evidence"
    strict = load(evidence / "strict-result.json")
    seal = load(evidence / "stage0c2c-seal-pair.json")
    capture = load(evidence / "stage0c2a-r-capture.json")
    pins = load(args.pins)
    framework = private / "UniXNU"
    device = private / "device"
    payload_source = framework / "scripts/unixnu/payload.py"
    patch = args.pins.with_name("stage0c2b-resume-packaging.patch")
    need(digest(payload_source) == pins["payload_before"] and digest(patch) == pins["patch"], "packaging source preimage")
    subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(framework), "apply", str(patch)], check=True)
    need(digest(payload_source) == pins["payload_after"], "packaging source result")
    sys.path.insert(0, str(framework / "scripts"))
    from unixnu.cli import parser
    from unixnu.config import Context
    from unixnu.payload import build

    seed_path = args.seed.resolve()
    try:
        seed_bytes = seed_path.read_bytes()
        with TemporaryDirectory(prefix="stage0c3-fat-", dir=temp) as directory:
            sandbox = Path(directory)
            ctx = Context(parser().parse_args(["status", "-D", str(device), "--os", "27",
                        "--out", str(private / "out"), "--config", str(private / "build.toml"),
                        "--uefi", str(private / "uefi-sheng"), "--data-ramdisk", str(seed_path), "--unique-chip-id", "00000001"]))
            work = private / "out/sheng/ipados-27.0.1-24A446/sheng_ipados27"
            need(ctx.work == work and ctx.tree == work / "tree", "packaging selected another build")
            raw = work / "kernel/kernel.macho"
            sealed = temp / "stage0c2c-private-sealed.macho"
            before, after = identity(raw), identity(sealed)
            need(before == dict(bytes=strict["candidate_bytes"], sha256=strict["candidate_sha256"])
                 and digest(raw.with_suffix(".map.json")) == strict["map_sha256"]
                 and after == dict(bytes=seal["bytes"], sha256=seal["after_sha256"])
                 and before["sha256"] == seal["before_sha256"] and seal["sealed_parser"] == "ACCEPT"
                 and before == {key: capture["candidate"][key] for key in ("bytes", "sha256")}, "packaging candidate")
            policy = ctx.tree / "build/sheng-source-storage/root-policies.bin"
            policy_pin = identity(policy)
            storage = load(policy.with_name("report.json"))
            need(storage["policy_bundle_sha256"] == policy_pin["sha256"]
                 and HEX.fullmatch(storage["trusted_key_sha256"]), "same-build root policies")

            admission = admit_production_seed(seed_bytes, args.approval_sha256, policy_pin["sha256"])
            (evidence / "stage0c3-seed-admission.json").write_text(json.dumps(admission, indent=2) + "\n", encoding="utf-8")

            spec = ctx.board["payload"]
            for key in ("install", "panic_screen", "entry_probe_reset_delay", "prepatch_fileset_static_if", "tools"):
                spec.pop(key, None)
            spec.update(loader="firmware", title="Stage 0C-3 Production Binding", root_policies=str(policy),
                        resume_only_storage_kernel_sha256=before["sha256"],
                        resume_only_storage_sealed_kernel_sha256=after["sha256"],
                        resume_only_storage_seed_sha256=EXPECTED_SEED_SHA,
                        resume_only_storage_seed_bytes=SEED_LOGICAL,
                        resume_only_storage_root_policies_sha256=policy_pin["sha256"])
            spec["kernel_args"] = [arg for arg in spec["kernel_args"]
                                   if arg.lstrip("-").split("=", 1)[0] not in {"data-persist", "data-wal-v2", "log", "gpu-addon", "data-reset"}]
            spec["kernel_args"] += ["data-persist=2", "data-wal-v2=1", "log=0"]
            ctx.work = sandbox / "package"
            ctx.logs = sandbox / "logs"
            image = build(ctx, sealed)
            pack_report = load(image.with_suffix(".json"))
            readback = sandbox / "readback"
            extract_volume(image, readback)
            files = audit_directory(readback, after, policy_pin, pack_report)

            parser_path = temp / "darwinboot-parser"
            need(digest(parser_path) == load(temp / "stage0c2a-r-audit-runtime.json")["parser_sha256"], "FAT parser identity")
            with (readback / KERNEL).open("rb") as stream:
                parsed = subprocess.run([parser_path], stdin=stream, capture_output=True, check=True).stdout
            match = re.fullmatch(rb"DarwinBoot parser PASS root_segments=(\d+) span=(\d+) entry=([0-9a-f]+)\n", parsed)
            need(match and dict(root_segments=int(match[1]), span=int(match[2]), entry=int(match[3], 16))
                 == capture["parser_summary"], "FAT input geometry")

            assets = args.pins.parent
            cmd_2c = [
                sys.executable, "-B", str(assets / "audit-stage0c3-2c.py"),
                "--candidate", str(sealed),
                "--adt", str(readback / ADT),
                "--kc-image", str(assets / "kc_image.py"),
                "--audit-2c", str(assets / "audit-stage0c2c.py"),
                "--out-dir", str(evidence),
            ]
            if args.objdump:
                cmd_2c.extend(["--objdump", args.objdump])
            subprocess.run(cmd_2c, check=True)

            row = dict(
                track=TRACK,
                static_result="PASS",
                production_inputs=True,
                loadable=False,
                runtime_qualified=False,
                raw_kernel=before,
                sealed_kernel=after,
                map_sha256=strict["map_sha256"],
                root_policy_source="same-build-storage-report",
                run_s_id=args.run_s_id,
                seed_approval_sha256=args.approval_sha256,
                seed=dict(kind="production-48g-apfs", logical_bytes=SEED_LOGICAL,
                          packed_bytes=EXPECTED_SEED_BYTES, sha256=EXPECTED_SEED_SHA),
                fat=identity(image),
                files=files,
                darwinboot="ACCEPT",
                final_efi_map="NOT_OBSERVED",
                device="NO-GO",
            )
            validate_receipt(row, strict, seal)
            (evidence / "stage0c3-fat.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    finally:
        seed_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
