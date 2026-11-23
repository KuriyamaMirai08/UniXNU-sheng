#!/usr/bin/env python3
"""Host tests for Stage 0C-3 2D/2E persistent ledger prototype with power-loss injection."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_proto as lp


class PowerLossDisk:
    def __init__(self, fail_on_write: int | None = None, half_write: bool = False):
        self.blocks: dict[int, bytes] = {}
        self.writes = 0
        self.syncs = 0
        self.fail_on_write = fail_on_write
        self.half_write = half_write

    def write_block(self, lba: int, data: bytes):
        self.writes += 1
        if self.fail_on_write is not None and self.writes == self.fail_on_write:
            if self.half_write:
                self.blocks[lba] = data[:2048] + b"\xff" * 2048
            raise IOError("injected power loss")
        self.blocks[lba] = data

    def read_block(self, lba: int) -> bytes:
        if lba not in self.blocks:
            return bytes(lp.BLOCK)
        return self.blocks[lba]

    def sync(self):
        self.syncs += 1


def make_real_48g_binding() -> lp.LedgerBinding:
    # Exact planned LBA geometry from 新GPT分区规划.json and storage-audit-48-64.json
    return lp.LedgerBinding(
        disk_id=str(uuid.UUID("11111111-2222-3333-4444-555555555555")),
        partition_id=str(uuid.UUID("22222222-3333-4444-5555-666666666666")),
        partition_type="0fc63daf-8483-4772-8e79-3d69d8477de4",
        lun=0,
        block_bytes=4096,
        capacity=64007168,
        partition_first=36649472,
        partition_last=64007162,
        root_end_exclusive=40495616,
        window_first=51120379,
        window_blocks=12624640,
        seed_sha256="a" * 64,
        seed_logical_bytes=48 << 30,
        preimage_sha256="b" * 64,
        epoch=1,
        transaction_id=str(uuid.UUID("33333333-4444-5555-6666-777777777777")),
    )


def expect_fail(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"Expected rejection for {label}")


def main():
    b = make_real_48g_binding()
    ledger_first, ledger_blocks = lp.compute_ledger_region(
        b.root_end_exclusive, b.window_first, b.partition_first
    )
    assert ledger_first == 51119339 and ledger_blocks == 16
    assert ledger_first >= 40495616 and ledger_first + ledger_blocks <= 51119355

    # 1. Overlap checks (root and guard)
    expect_fail(lambda: lp.compute_ledger_region(51119340, b.window_first, b.partition_first), "root-overlap")
    expect_fail(lambda: lp.compute_ledger_region(b.root_end_exclusive, 36649472 + 1024, 36649472), "partition-underflow")

    # 2. Normal two-phase commit + read-only Recovery verify
    disk = PowerLossDisk()
    lp.write_two_phase(disk, ledger_first, 1, b)
    res = lp.read_verify_ledger(disk, b, min_epoch=1, readonly_recovery=True)
    assert res["status"] == "PASS_SYNTHETIC"
    assert res["trusted_media_observation"] == "NOT_OBSERVED"
    assert res["install_allowed"] is False

    # 3. Power-loss injection at every write boundary (writes 1..4), full and half-written
    for w in (1, 2, 3, 4):
        for half in (False, True):
            d = PowerLossDisk(fail_on_write=w, half_write=half)
            try:
                lp.write_two_phase(d, ledger_first, 1, b)
                raise AssertionError("expected IOError")
            except IOError:
                pass
            if w <= 3:
                expect_fail(lambda d=d: lp.read_verify_ledger(d, b, 1, readonly_recovery=False), f"torn-w{w}-half{half}")
            else:
                # Write 4 is copy B COMMITTED; copy A is already COMMITTED so normal boot accepts,
                # while strict recovery detects mismatch between copy A and copy B.
                lp.read_verify_ledger(d, b, 1, readonly_recovery=False)
                expect_fail(lambda d=d: lp.read_verify_ledger(d, b, 1, readonly_recovery=True), f"recovery-mismatch-w{w}")

    # 4. Negative cases: replay/stale epoch, wrong disk, split-brain same seq/phase
    expect_fail(lambda: lp.read_verify_ledger(disk, b, min_epoch=2), "stale-epoch")
    expect_fail(lambda: lp.read_verify_ledger(disk, replace(b, disk_id=str(uuid.uuid4())), min_epoch=1), "wrong-disk")

    split = PowerLossDisk()
    split.write_block(ledger_first + 0, lp.encode_record(1, lp.PHASE_COMMITTED, b))
    split.write_block(ledger_first + 1, lp.encode_record(1, lp.PHASE_COMMITTED, replace(b, epoch=9)))
    expect_fail(lambda: lp.read_verify_ledger(split, b, min_epoch=1), "split-brain")

    out = Path(__file__).resolve().parent / "ledger-proto-results.json"
    out.write_text(json.dumps({
        "status": "PASS_SYNTHETIC",
        "ledger_first_lba": ledger_first,
        "ledger_blocks": ledger_blocks,
        "guard_first_lba": b.window_first - lp.GUARD_BLOCKS,
        "root_end_exclusive": b.root_end_exclusive,
        "power_loss_boundaries_tested": 8,
        "negative_cases_passed": True,
        "trusted_media_observation": "NOT_OBSERVED",
        "install_allowed": False,
    }, indent=2) + "\n", encoding="utf-8")
    print("PASS ledger_proto all power-loss and negative tests")


if __name__ == "__main__":
    main()
