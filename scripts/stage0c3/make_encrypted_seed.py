#!/usr/bin/env python3
"""Stage 0C-3 Run S: build, verify, and encrypt the 48 GiB production APFS Data seed."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BLOCK = 4096
GIB_48 = 48 << 30
AAD = b"unixnu-sheng-seed-20261123"
IPSW_SPEC = {
    "url": "https://updates.cdn-apple.com/2026FallFCS/6074e110-d48d-40c2-b0e8-b611520941a3/iPad17,1,iPad17,2,iPad17,3,iPad17,4_27.0.1_24A446_Restore.ipsw",
    "product": "iPad17,3",
    "version": "27.0.1",
    "build": "24A446",
    "device_class": "j820ap",
    "chip_id": 33090,
    "board_id": 12,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def packed_pages(blob):
    require(32 <= len(blob) <= 256 << 20, "packed size outside 32..256 MiB")
    magic, version, block, logical, count = struct.unpack_from("<8sIIQQ", blob)
    require((magic, version, block) == (b"DBRDISK1", 1, BLOCK) and 0 < logical <= 1 << 40
            and logical % BLOCK == 0 and 0 < count <= min(65536, (len(blob) - 32) // 16), "packed header")
    cursor, past = 32 + count * 16, 0
    pages = {}
    for off, size in struct.iter_unpack("<QQ", blob[32:cursor]):
        require(size > 0 and (off | size) % BLOCK == 0 and past <= off <= off + size <= logical
                and cursor + size <= len(blob), "invalid packed extent")
        for delta in range(0, size, BLOCK):
            at = cursor + delta
            pages[(off + delta) // BLOCK] = blob[at:at + BLOCK]
        cursor += size
        past = off + size
    require(cursor == len(blob), "trailing packed data")
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


def space_manager(logical, pages):
    def nx_valid(block):
        return (valid_object(block, 1) and block[32:36] == b"NXSB" and
                struct.unpack_from("<IQ", block, 36) == (BLOCK, logical // BLOCK))

    start = pages.get(0)
    require(nx_valid(start), "invalid container superblock")
    desc_count, data_count, desc_base, data_base = struct.unpack_from("<IIqq", start, 104)
    require(0 < desc_count < 1 << 31 and 0 < data_count < 1 << 31
            and 0 < desc_base <= logical // BLOCK - desc_count and 0 < data_base <= logical // BLOCK - data_count,
            "unsupported or invalid checkpoint geometry")
    candidates = [(struct.unpack_from("<Q", p, 16)[0], lba, p) for lba, p in pages.items()
                  if desc_base <= lba < desc_base + desc_count and nx_valid(p)]
    require(bool(candidates), "no valid checkpoint superblock")
    xid, lba, checkpoint = max(candidates)
    require(checkpoint[72:88] == start[72:88] and checkpoint[104:128] == start[104:128], "checkpoint identity")
    index, length, data_index, data_length, space_oid = struct.unpack_from("<IIIIQ", checkpoint, 136)
    require(0 <= index < desc_count and 2 <= length <= desc_count and 0 <= data_index < data_count
            and 0 < data_length <= data_count and desc_base + (index + length - 1) % desc_count == lba,
            "checkpoint indices")

    matches = []
    for delta in range(length - 1):
        mapping = pages.get(desc_base + (index + delta) % desc_count)
        require(valid_object(mapping, 12) and struct.unpack_from("<Q", mapping, 16)[0] == xid, "invalid checkpoint map")
        flags, count = struct.unpack_from("<II", mapping, 32)
        require(flags == int(delta == length - 2) and 40 + count * 40 <= BLOCK, "invalid checkpoint map bounds")
        for dtype, _, size, _, fs, oid, address in struct.iter_unpack("<IIIIQQQ", mapping[40:40 + 40 * count]):
            if dtype & 0xFFFF == 5 and oid == space_oid and fs == 0:
                require(size == BLOCK and data_base <= address < data_base + data_count
                        and address in pages, "missing checkpoint space manager")
                matches.append(pages[address])
    require(len(matches) == 1 and valid_object(matches[0], 5) and struct.unpack_from("<Q", matches[0], 16)[0] == xid,
            "invalid space manager")
    block_size, _, blocks, _, _, free_blocks = struct.unpack_from("<IIQQQQ", matches[0], 32)
    require(block_size == BLOCK and blocks == logical // BLOCK and free_blocks <= blocks, "space manager bounds")
    return dict(
        xid=xid,
        blocks=blocks,
        free_blocks=free_blocks,
        nonfree_main_bytes=(blocks - free_blocks) * BLOCK,
        container_id=start[72:88].hex(),
    )


def single_volume_uuid(pages):
    identities = set()
    for block in pages.values():
        if block[32:36] == b"APSB":
            identities.add(str(uuid.UUID(bytes=bytes(block[240:256]))).upper())
    require(len(identities) == 1, f"expected 1 APSB volume UUID, found {len(identities)}")
    return identities.pop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    key_b64 = os.environ.get("UNIXNU_SHENG_SEED_KEY_20261123", "").strip()
    key = base64.b64decode(key_b64)
    require(len(key) == 32, "seed encryption key must be 32 bytes")

    unixnu = args.unixnu.resolve()
    (unixnu / "build").mkdir(parents=True, exist_ok=True)
    work = args.work.resolve()
    out = args.out.resolve()
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(unixnu / "scripts"))
    from unixnu.ipsw import Ipsw

    ctx = SimpleNamespace(
        option_text=lambda *a: None,
        board={"ipsw": IPSW_SPEC},
        out_root=work / "out",
    )
    ipsw = Ipsw(ctx)
    manifest_bytes = ipsw.zip.read("BuildManifest.plist")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    os_dmg = ipsw.disk_image("OS")

    mount = work / "os-mount"
    mount.mkdir(parents=True, exist_ok=True)
    seed_path = work / "data.dbr"
    if seed_path.exists():
        seed_path.unlink()

    attached = plistlib.loads(subprocess.check_output(
        ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), "-plist", str(os_dmg)]
    ))
    dev = attached["system-entities"][0]["dev-entry"]
    try:
        subprocess.run(
            ["sudo", sys.executable, str(unixnu / "scripts/make-data-seed.py"),
             str(mount), str(seed_path), "--gib", "48", "--build", "24A446", "--skip-setup"],
            check=True,
        )
    finally:
        subprocess.run(["hdiutil", "detach", dev], check=True)

    raw_bytes = seed_path.read_bytes()
    logical, pages = packed_pages(raw_bytes)
    require(logical == GIB_48, f"logical size {logical} != {GIB_48}")
    stats = space_manager(logical, pages)
    vol_uuid = single_volume_uuid(pages)
    packed_sha = hashlib.sha256(raw_bytes).hexdigest()

    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, raw_bytes, AAD)
    enc_blob = nonce + ciphertext
    enc_path = out / "data.dbr.enc"
    enc_path.write_bytes(enc_blob)
    enc_sha = hashlib.sha256(enc_blob).hexdigest()

    # Scrub plaintext seed and decrypted OS image from runner work dir
    seed_path.unlink(missing_ok=True)
    shutil.rmtree(work / "out", ignore_errors=True)

    ipsw_ver = subprocess.check_output(["ipsw", "version"], text=True).strip()
    receipt = {
        "purpose": "production-seed-generation",
        "packed_sha256": packed_sha,
        "packed_bytes": len(raw_bytes),
        "logical_bytes": logical,
        "apfs_container_id": stats["container_id"],
        "volume_uuid": vol_uuid,
        "nonfree_main_bytes": stats["nonfree_main_bytes"],
        "xid": stats["xid"],
        "skip_setup": True,
        "encrypted_file": enc_path.name,
        "encrypted_sha256": enc_sha,
        "encrypted_bytes": len(enc_blob),
        "cipher": "AES-256-GCM",
        "nonce_bytes": 12,
        "aad": AAD.decode("ascii"),
        "ipsw_url": IPSW_SPEC["url"],
        "build": IPSW_SPEC["build"],
        "build_manifest_sha256": manifest_sha,
        "ipsw_tool_version": ipsw_ver,
        "runner_image": os.environ.get("ImageVersion", "missing"),
        "sw_vers_build": subprocess.check_output(["sw_vers", "-buildVersion"], text=True).strip(),
    }
    (out / "seed-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packed_sha256": packed_sha, "packed_bytes": len(raw_bytes), "logical_bytes": logical, "apfs_container_id": stats["container_id"]}))


if __name__ == "__main__":
    main()
