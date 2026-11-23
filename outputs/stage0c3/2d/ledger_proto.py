#!/usr/bin/env python3
"""Stage 0C-3 2D/2E persistent first-install ownership ledger prototype.

Stores dual-copy, CRC32C + SHA-256 protected records in a 16-block region
strictly between the root images end and the 1024-block WAL guard:
  [window_first - 1024 - 16, window_first - 1024)
Does not alter PersistWalV2.h root blocks or the W window formula.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import struct
from uuid import UUID

BLOCK = 4096
GUARD_BLOCKS = 1024
LEDGER_BLOCKS = 16
MAGIC = b"SHNGLDG1"
VERSION = 1
PHASE_INTENT = 1
PHASE_COMMITTED = 2
HEADER_FMT = "<8sIIQII"  # magic(8), version(4), phase(4), seq(8), payload_len(4), crc32c(4) -> 32 B
HEADER_SIZE = struct.calcsize(HEADER_FMT)
SHA_SIZE = 32
META_SIZE = HEADER_SIZE + SHA_SIZE  # 64 B


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if (crc & 1) else 0)
    return crc ^ 0xFFFFFFFF


@dataclass(frozen=True)
class LedgerBinding:
    disk_id: str
    partition_id: str
    partition_type: str
    lun: int
    block_bytes: int
    capacity: int
    partition_first: int
    partition_last: int
    root_end_exclusive: int
    window_first: int
    window_blocks: int
    seed_sha256: str
    seed_logical_bytes: int
    preimage_sha256: str
    epoch: int
    transaction_id: str

    def canonical_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("ascii")


def compute_ledger_region(root_end_exclusive: int, window_first: int, partition_first: int) -> tuple[int, int]:
    guard_first = window_first - GUARD_BLOCKS
    ledger_first = guard_first - LEDGER_BLOCKS
    if ledger_first < partition_first or ledger_first < root_end_exclusive:
        raise ValueError("ledger region overlaps root images or precedes partition")
    if ledger_first + LEDGER_BLOCKS > guard_first:
        raise ValueError("ledger region overlaps WAL guard")
    return ledger_first, LEDGER_BLOCKS


def encode_record(seq: int, phase: int, binding: LedgerBinding) -> bytes:
    if phase not in (PHASE_INTENT, PHASE_COMMITTED) or seq <= 0:
        raise ValueError("invalid ledger seq or phase")
    payload = binding.canonical_bytes()
    if META_SIZE + len(payload) > BLOCK:
        raise ValueError("ledger payload exceeds 4096 B block")
    payload_sha = hashlib.sha256(payload).digest()
    pre = struct.pack(HEADER_FMT, MAGIC, VERSION, phase, seq, len(payload), 0) + payload_sha + payload
    crc = crc32c(pre)
    block = struct.pack(HEADER_FMT, MAGIC, VERSION, phase, seq, len(payload), crc) + payload_sha + payload
    return block.ljust(BLOCK, b"\x00")


def decode_record(block: bytes) -> tuple[int, int, dict, bytes]:
    if len(block) != BLOCK:
        raise ValueError("short block")
    magic, ver, phase, seq, plen, stored_crc = struct.unpack_from(HEADER_FMT, block, 0)
    if magic != MAGIC or ver != VERSION or phase not in (PHASE_INTENT, PHASE_COMMITTED) or seq <= 0:
        raise ValueError("invalid ledger header")
    if plen == 0 or META_SIZE + plen > BLOCK:
        raise ValueError("invalid payload length")
    if any(b != 0 for b in block[META_SIZE + plen:]):
        raise ValueError("non-zero trailing bytes")
    payload_sha = block[HEADER_SIZE:META_SIZE]
    payload = block[META_SIZE:META_SIZE + plen]
    zeroed = struct.pack(HEADER_FMT, magic, ver, phase, seq, plen, 0) + payload_sha + payload
    if crc32c(zeroed) != stored_crc:
        raise ValueError("CRC32C mismatch")
    if hashlib.sha256(payload).digest() != payload_sha:
        raise ValueError("SHA-256 mismatch")
    return seq, phase, json.loads(payload.decode("ascii")), payload


def write_two_phase(disk, ledger_first: int, seq: int, binding: LedgerBinding):
    """Two-phase durable write: INTENT+sync, then COMMITTED+sync to both copies."""
    intent = encode_record(seq, PHASE_INTENT, binding)
    disk.write_block(ledger_first + 0, intent)
    disk.sync()
    disk.write_block(ledger_first + 1, intent)
    disk.sync()
    committed = encode_record(seq, PHASE_COMMITTED, binding)
    disk.write_block(ledger_first + 0, committed)
    disk.sync()
    disk.write_block(ledger_first + 1, committed)
    disk.sync()


def read_verify_ledger(disk, expected: LedgerBinding, min_epoch: int, readonly_recovery: bool = False) -> dict:
    ledger_first, _ = compute_ledger_region(
        expected.root_end_exclusive, expected.window_first, expected.partition_first
    )
    copies = []
    errors = []
    for idx in (0, 1):
        try:
            blk = disk.read_block(ledger_first + idx)
            copies.append((idx, *decode_record(blk)))
        except Exception as exc:
            errors.append((idx, str(exc)))

    if not copies:
        raise ValueError(f"no valid ledger copy: {errors}")

    # Detect same-seq/same-phase split-brain with different payloads
    if len(copies) == 2:
        (_, s0, p0, _, raw0), (_, s1, p1, _, raw1) = copies
        if s0 == s1 and p0 == p1 and raw0 != raw1:
            raise ValueError("split-brain: both copies share seq/phase with different payloads")

    # Select highest (seq, phase)
    best = max(copies, key=lambda x: (x[1], x[2]))
    idx, seq, phase, rec, _ = best
    if readonly_recovery and (
        len(copies) != 2
        or (copies[0][1], copies[0][2], copies[0][4]) != (copies[1][1], copies[1][2], copies[1][4])
        or phase != PHASE_COMMITTED
    ):
        raise ValueError("recovery requires two identical COMMITTED ledger copies")
    if phase != PHASE_COMMITTED:
        raise ValueError("ledger transaction not COMMITTED (torn write or INTENT-only)")

    exp_dict = asdict(expected)
    for k in ("disk_id", "partition_id", "partition_type", "lun", "block_bytes",
              "capacity", "partition_first", "partition_last", "window_first",
              "window_blocks", "seed_sha256", "seed_logical_bytes", "preimage_sha256"):
        if rec.get(k) != exp_dict[k]:
            raise ValueError(f"binding mismatch on {k}")
    if rec["epoch"] < min_epoch:
        raise ValueError("stale or replayed epoch")
    if UUID(rec["transaction_id"]).int == 0:
        raise ValueError("zero transaction_id")

    return {
        "status": "PASS_SYNTHETIC",
        "ledger_first_lba": ledger_first,
        "ledger_blocks": LEDGER_BLOCKS,
        "seq": seq,
        "phase": "COMMITTED",
        "epoch": rec["epoch"],
        "transaction_id": rec["transaction_id"],
        "trusted_media_observation": "NOT_OBSERVED",
        "install_allowed": False,
    }
