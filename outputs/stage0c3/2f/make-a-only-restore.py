#!/usr/bin/env python3
"""Generate a strict A-only fastboot restore script after AVB hash verification.

DO NOT RUN automatically — device is NO-GO and requires separate user authorization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ALLOWED_A_PARTITIONS = frozenset({
    "boot_a",
    "init_boot_a",
    "vendor_boot_a",
    "dtbo_a",
    "vbmeta_a",
    "vbmeta_system_a",
})

FORBIDDEN_PARTITION_TOKENS = (
    "_ab",
    "userdata",
    "persist",
    "modem",
    "fsg",
    "efs",
    "gpt",
)

FORBIDDEN_CMD_PATTERNS = (
    r"_b(?=\s|$)",
    r"_ab(?=\s|$)",
    r"\buserdata\b",
    r"\bpersist\b",
    r"\bmodem",
    r"\bfsg\b",
    r"\befs\b",
    r"\bgpt\b",
    r"--set-active",
    r"\berase\b",
    r"\bformat\b",
    r"(?:^|\s)-w(?:\s|$)",
    r"\boem\s+lock\b",
    r"\bflashing\s+lock\b",
)


def validate_target_partition(part: str, avb_bound: set[str]):
    low = part.lower().strip()
    if low.endswith("_b") or any(tok in low for tok in FORBIDDEN_PARTITION_TOKENS):
        raise ValueError(f"forbidden partition or operation: {part}")
    if low not in ALLOWED_A_PARTITIONS:
        raise ValueError(f"partition not in strict A-only whitelist: {part}")
    base = low[:-2]
    if base not in avb_bound:
        raise ValueError(f"partition {part} not proven bound in AVB descriptors")


def validate_command_line(line: str):
    low = line.lower().strip()
    for pat in FORBIDDEN_CMD_PATTERNS:
        if re.search(pat, low):
            raise ValueError(f"forbidden pattern '{pat}' in command: {line}")
    if not re.fullmatch(r'fastboot flash [a-z0-9_]+_a (?:"[^"]+"|\S+)', line.strip()):
        raise ValueError(f"command does not match strict 'fastboot flash <part>_a <image>' pattern: {line}")


def build_restore_script(images_dir: Path, avb_doc: dict, image_hashes: dict[str, str],
                         manifest: list[tuple[str, Path]]) -> str:
    avb_bound = {"vbmeta", "vbmeta_system"}
    for img_name in ("vbmeta", "vbmeta_system"):
        for desc in avb_doc["images"][img_name]["descriptors"]:
            avb_bound.add(desc["partition"])

    lines = [
        "# DO NOT RUN — device NO-GO (requires separate user authorization)",
        "# Strict A-only Android restore script; never touches _b, userdata, persist, modem/fsg/efs, or GPT.",
        "set -euo pipefail",
    ]
    for part, rel_img in manifest:
        validate_target_partition(part, avb_bound)
        img_path = (images_dir / rel_img).resolve()
        if not img_path.is_file():
            raise FileNotFoundError(f"missing stock image: {img_path}")
        actual_sha = hashlib.sha256(img_path.read_bytes()).hexdigest()
        expected_sha = image_hashes.get(part)
        if not expected_sha or actual_sha != expected_sha:
            raise ValueError(f"AVB/manifest SHA-256 mismatch for {part}: {actual_sha} != {expected_sha}")
        cmd = f"fastboot flash {part} \"{img_path}\""
        validate_command_line(cmd)
        lines.append(cmd)
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images-dir", type=Path, required=True)
    ap.add_argument("--avb-json", type=Path, required=True)
    ap.add_argument("--hashes-json", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    avb_doc = json.loads(args.avb_json.read_text(encoding="utf-8"))
    hashes = json.loads(args.hashes_json.read_text(encoding="utf-8"))
    manifest = [(part, Path(info["file"])) for part, info in hashes.items()]
    expected = {part: info["sha256"] for part, info in hashes.items()}
    script = build_restore_script(args.images_dir, avb_doc, expected, manifest)
    args.out.write_text(script, encoding="utf-8")
    print(f"Wrote A-only restore script to {args.out}")


if __name__ == "__main__":
    main()
