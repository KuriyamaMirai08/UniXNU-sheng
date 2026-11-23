#!/usr/bin/env python3
"""Unit tests verifying make-a-only-restore.py refuses all dangerous partitions and flags."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("make_a_only_restore", HERE / "make-a-only-restore.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

AVB_PATH = Path(r"C:\Users\13463\Documents\ChatGPT\双系统\stage0c2-local-repairs\outputs\verification-20261121\2f-stock-avb.json")


def expect_reject(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"Expected rejection for {label}")


def main():
    avb = json.loads(AVB_PATH.read_text(encoding="utf-8"))
    avb_bound = {"vbmeta", "vbmeta_system", "boot", "init_boot", "vendor_boot", "dtbo"}

    for bad_part in (
        "boot_b", "vbmeta_b", "boot_ab", "userdata", "persist",
        "modem_a", "modem_b", "fsg", "efs", "gpt", "abl_a", "uefi_a",
    ):
        expect_reject(lambda p=bad_part: MOD.validate_target_partition(p, avb_bound), bad_part)

    for bad_cmd in (
        "fastboot flash boot_b boot.img",
        "fastboot --set-active=a",
        "fastboot erase userdata",
        "fastboot -w",
        "fastboot format userdata",
        "fastboot flash userdata userdata.img",
        "fastboot oem lock",
    ):
        expect_reject(lambda c=bad_cmd: MOD.validate_command_line(c), bad_cmd)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        hashes = {}
        manifest = []
        for part in ("boot_a", "init_boot_a", "vendor_boot_a", "dtbo_a", "vbmeta_a", "vbmeta_system_a"):
            p = d / f"{part}.img"
            data = f"synthetic-{part}".encode()
            p.write_bytes(data)
            hashes[part] = hashlib.sha256(data).hexdigest()
            manifest.append((part, Path(p.name)))
        script = MOD.build_restore_script(d, avb, hashes, manifest)
        assert script.startswith("# DO NOT RUN — device NO-GO")
        cmd_lines = [ln for ln in script.splitlines() if ln.startswith("fastboot ")]
        assert len(cmd_lines) == 6
        assert all("_b " not in ln and "userdata" not in ln and "erase" not in ln for ln in cmd_lines)

        # Tampered hash must be rejected
        bad_hashes = dict(hashes, boot_a="0" * 64)
        expect_reject(lambda: MOD.build_restore_script(d, avb, bad_hashes, manifest), "tampered-hash")

    print("PASS make-a-only-restore negative and positive tests")


if __name__ == "__main__":
    main()
