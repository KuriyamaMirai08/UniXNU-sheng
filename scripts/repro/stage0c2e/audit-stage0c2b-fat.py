"""Package one in-run candidate into a disposable, calibration-only FAT and read it back."""
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


TRACK = "2b-fat"
SEED_SIZE = 48 << 30
SEED = struct.pack("<8sIIQQQQ", b"DBRDISK1", 1, 4096, SEED_SIZE, 1, 0, 4096) + bytes(4096)
SEED_SHA = hashlib.sha256(SEED).hexdigest()
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


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path):
    return dict(bytes=path.stat().st_size, sha256=digest(path))


def menu_matches(data, command_line):
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
    need(boot["args"] == command_line and recovery["args"] == " ".join(
         [*expected_recovery, "data-persist=1", "log=0"])
         and boot["args"].split().count("data-wal-v2=1") == 1, "FAT menu arguments")


def check_adt(data):
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


def audit_directory(directory, sealed, policy, pack_report):
    files = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file()}
    need(set(files) == PATHS, "FAT file inventory")
    need(identity(files[KERNEL]) == sealed and identity(files[ROOT]) == policy,
         "FAT kernel or root policy changed")
    need(files[DATA].stat().st_size == len(SEED) and digest(files[DATA]) == SEED_SHA, "FAT seed changed")
    need(digest(files[ADT]) == pack_report["adt_sha256"], "FAT ADT changed")
    check_adt(files[ADT].read_bytes())
    menu_matches(files[MENU].read_bytes(), pack_report["kernel_args"])
    return {name: identity(path) for name, path in sorted(files.items())}


def extract_volume(image, directory):
    directory.mkdir()
    subprocess.run(["mcopy", "-s", "-i", str(image.resolve()), "::/*", "."], cwd=directory,
                   env=dict(os.environ, MTOOLS_SKIP_CHECK="1", TZ="UTC"), capture_output=True, check=True)


def validate_receipt(row, strict, seal):
    fields = {"track", "static_result", "production", "raw_kernel", "sealed_kernel", "map_sha256",
              "root_policy_source", "seed", "fat", "files", "darwinboot", "final_efi_map", "device"}
    need(set(row) == fields and row["track"] == TRACK and row["static_result"] == "PASS"
         and row["production"] is False and row["final_efi_map"] == "NOT_OBSERVED" and row["device"] == "NO-GO",
         "FAT receipt scope")
    need(row["raw_kernel"] == dict(bytes=strict["candidate_bytes"], sha256=strict["candidate_sha256"])
         and row["raw_kernel"]["sha256"] == seal["before_sha256"] and row["map_sha256"] == strict["map_sha256"]
         and row["sealed_kernel"] == dict(bytes=seal["bytes"], sha256=seal["after_sha256"])
         and row["darwinboot"] == "ACCEPT", "FAT receipt lineage")
    need(row["root_policy_source"] == "same-build-storage-report"
         and row["seed"] == dict(kind="calibration-non-apfs", logical_bytes=SEED_SIZE, sha256=SEED_SHA),
         "FAT receipt input scope")
    files = row["files"]
    need(set(files) == PATHS and files[KERNEL] == row["sealed_kernel"]
         and files[DATA] == dict(bytes=len(SEED), sha256=SEED_SHA), "FAT receipt inventory")
    for record in [row["fat"], *files.values()]:
        need(set(record) == {"bytes", "sha256"} and type(record["bytes"]) is int
             and 0 < record["bytes"] <= 2 << 30 and HEX.fullmatch(record["sha256"]), "FAT receipt identity")


def load(path):
    return json.loads(path.read_bytes())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("temp", type=Path)
    cli.add_argument("pins", type=Path)
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

    with TemporaryDirectory(prefix="stage0c2b-no-deploy-", dir=temp) as directory:
        sandbox = Path(directory)
        seed = sandbox / "test-packed-non-apfs.bin"
        seed.write_bytes(SEED)
        ctx = Context(parser().parse_args(["status", "-D", str(device), "--os", "27",
                    "--out", str(private / "out"), "--config", str(private / "build.toml"),
                    "--uefi", str(private / "uefi-sheng"), "--data-ramdisk", str(seed), "--unique-chip-id", "00000001"]))
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
        need(storage["policy_bundle_sha256"] == policy_pin["sha256"] and
             HEX.fullmatch(storage["trusted_key_sha256"]), "same-build root policies")
        spec = ctx.board["payload"]
        for key in ("install", "panic_screen", "entry_probe_reset_delay", "prepatch_fileset_static_if", "tools"):
            spec.pop(key, None)
        spec.update(loader="firmware", title="Calibration only", root_policies=str(policy),
                    resume_only_storage_kernel_sha256=before["sha256"],
                    resume_only_storage_sealed_kernel_sha256=after["sha256"],
                    resume_only_storage_seed_sha256=SEED_SHA, resume_only_storage_seed_bytes=SEED_SIZE,
                    resume_only_storage_root_policies_sha256=policy_pin["sha256"])
        spec["kernel_args"] = [arg for arg in spec["kernel_args"]
                               if arg.lstrip("-").split("=", 1)[0] not in {"data-persist", "data-wal-v2", "log", "gpu-addon"}]
        spec["kernel_args"] += ["data-persist=2", "data-wal-v2=1", "log=0"]
        ctx.work = sandbox / "package"
        ctx.logs = sandbox / "logs"
        image = build(ctx, sealed)
        pack_report = load(image.with_suffix(".json"))
        readback = sandbox / "readback"
        extract_volume(image, readback)
        files = audit_directory(readback, after, policy_pin, pack_report)
        parser_path = temp / "darwinboot-parser"
        need(digest(parser_path) == load(temp / "stage0c2a-r-audit-runtime.json")["parser_sha256"],
             "FAT parser identity")
        with (readback / KERNEL).open("rb") as stream:
            parsed = subprocess.run([parser_path], stdin=stream, capture_output=True, check=True).stdout
        match = re.fullmatch(rb"DarwinBoot parser PASS root_segments=(\d+) span=(\d+) entry=([0-9a-f]+)\n", parsed)
        need(match and dict(root_segments=int(match[1]), span=int(match[2]), entry=int(match[3], 16))
             == capture["parser_summary"], "FAT input geometry")
        row = dict(track=TRACK, static_result="PASS", production=False, raw_kernel=before, sealed_kernel=after,
                   map_sha256=strict["map_sha256"], root_policy_source="same-build-storage-report",
                   seed=dict(kind="calibration-non-apfs", logical_bytes=SEED_SIZE, sha256=SEED_SHA),
                   fat=identity(image), files=files, darwinboot="ACCEPT", final_efi_map="NOT_OBSERVED", device="NO-GO")
        validate_receipt(row, strict, seal)
    (evidence / "stage0c2b-fat.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
