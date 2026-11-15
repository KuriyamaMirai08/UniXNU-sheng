#!/usr/bin/env python3
"""Restore the exact installed seed and identity for this isolated candidate.

Inputs are authenticated encrypted bytes extracted from the prior installed
boot image. The unrelated Actions cache is never substituted for them.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import struct
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    contract = json.loads((repo / "scripts/sheng-candidate-input-contract.json").read_text())
    encrypted = (repo / "inputs/sheng-installed-input-20261115.aesgcm").read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != contract["encrypted_input_sha256"] or encrypted[:8] != b"SHNGCI01":
        raise ValueError("Installed candidate input identity changed")
    key = bytes.fromhex(os.environ.pop(contract["secret_name"]))
    plain = AESGCM(key).decrypt(encrypted[8:20], encrypted[20:], b"UniXNU-sheng installed input 20261115 v1")
    saved = json.loads(zlib.decompress(plain))
    data = zlib.decompress(base64.b64decode(saved["seed_zlib_base64"], validate=True))
    if hashlib.sha256(data).hexdigest() != contract["seed_sha256"] or len(data) != contract["encoded_bytes"]:
        raise ValueError("Restored installed Seed differs from its original boot payload")
    identity = struct.pack("<Q", int(saved["unique_chip_id"], 16))
    if hashlib.sha256(identity).hexdigest() != contract["unique_chip_id_sha256"] or saved["chip_id"] != contract["chip_id"]:
        raise ValueError("Restored identity differs from the installed boot ADT")
    spec = importlib.util.spec_from_file_location("seed_inspection", repo / "scripts/inspect-candidate-seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    receipt = module.inspect(data, contract["seed_uuid"])
    if saved["source_boot_sha256"] != contract["source_boot_sha256"]:
        raise ValueError("Installed input source boot changed")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "data.dbr").write_bytes(data)
    receipt.update(source_boot_sha256=contract["source_boot_sha256"],
                   identity_matches_installed=True, unrelated_seed_cache_used=False)
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("::add-mask::" + saved["unique_chip_id"])
    with open(os.environ["GITHUB_ENV"], "a") as stream:
        stream.write("UNIXNU_UNIQUE_CHIP_ID=" + saved["unique_chip_id"] + "\n")
        stream.write("SHENG_CANDIDATE_DATA=" + str((args.output / "data.dbr").resolve()) + "\n")
    print("Exact installed Seed and identity restored; no Data regeneration")


if __name__ == "__main__":
    main()
