#!/usr/bin/env python3
"""Record a restored installation seed without generating or modifying Data.

The packed extent checks follow the pinned DarwinBoot DBRDISK1 contract.
This is a new input receipt, not a replacement for missing historical evidence.
"""
import argparse
import hashlib
import json
import struct
import uuid
from pathlib import Path

PAGE = 4096


def inspect(blob, expected_uuid):
    if not 32 <= len(blob) <= 256 * 1024**2:
        raise ValueError("Packed seed input size is invalid")
    magic, version, page, logical, count = struct.unpack_from("<8sIIQQ", blob)
    if (magic, version, page) != (b"DBRDISK1", 1, PAGE):
        raise ValueError("Original seed is not a supported DBRDISK1 input")
    if not 0 < logical <= 1024**4 or logical % PAGE or count > 65536 or count > (len(blob) - 32) // 16:
        raise ValueError("Original seed geometry is invalid")
    cursor, end = 32 + 16 * count, 0
    identities, superblocks, extents = set(), [], []
    identity = hashlib.sha256(b"SHNGSEED2" + struct.pack("<Q", logical))
    for index in range(count):
        offset, length = struct.unpack_from("<QQ", blob, 32 + 16 * index)
        if (not length or (offset | length) % PAGE or offset < end or offset > logical or
                length > logical - offset or length > len(blob) - cursor):
            raise ValueError("Original seed contains an invalid packed extent")
        data = memoryview(blob)[cursor:cursor + length]
        extents.append(dict(offset=offset, length=length))
        for at in range(0, length, PAGE):
            block = bytes(data[at:at + PAGE])
            if any(block):
                identity.update(struct.pack("<Q", (offset + at) // PAGE) + block)
            if block[32:36] == b"APSB":
                volume_uuid = str(uuid.UUID(bytes=block[240:256])).upper()
                identities.add(volume_uuid)
                superblocks.append(dict(logical_offset=offset + at, volume_uuid=volume_uuid,
                                        sha256=hashlib.sha256(block).hexdigest()))
        cursor += length
        end = offset + length
    if cursor != len(blob):
        raise ValueError("Original seed contains trailing packed bytes")
    if identities != {str(uuid.UUID(expected_uuid)).upper()}:
        raise ValueError("Restored Data UUID does not match the installed sheng configuration")
    return dict(encoded_bytes=len(blob), encoded_sha256=hashlib.sha256(blob).hexdigest(),
                logical_bytes=logical, packed_extents=extents, data_volume_uuid=identities.pop(),
                seed_identity_v2=identity.hexdigest() if logical > 2 * 1024**3 else None,
                volume_superblocks=superblocks, installed_uuid_matches=True,
                historical_integrity_record_present=False, new_receipt=True,
                seed_regenerated=False, seed_modified=False, device_operations=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--expected-uuid", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    original = args.seed.read_bytes()
    report = inspect(original, args.expected_uuid)
    if args.seed.read_bytes() != original:
        raise ValueError("Seed input changed during inspection")
    (args.evidence / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.evidence / "data.dbr").write_bytes(original)
    print("Restored original Data seed: packed structure and installed volume UUID match")


if __name__ == "__main__":
    main()
