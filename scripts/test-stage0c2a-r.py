#!/usr/bin/env python3
"""Exercise the production parser with one sample and five controlled rejects."""

import argparse
import hashlib
import importlib.util
import json
import struct
import subprocess
from pathlib import Path

AUDIT_PATH = Path(__file__).with_name("audit-stage0c2a-r.py")
SPEC = importlib.util.spec_from_file_location("stage0c2a_r_audit", AUDIT_PATH)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
fileset_entries = AUDIT.fileset_entries
read_header = AUDIT.read_header
segments_for = AUDIT.segments_for


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--parser", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.sample.read_bytes()
    root = read_header(source, 0, "root")
    root_segments = segments_for(source, root, "root")
    entries = fileset_entries(source, root)
    entry = next(row for row in entries if row["id"] == "com.apple.kernel")
    member = read_header(source, entry["fileoff"], entry["id"])
    member_segments = segments_for(source, member, entry["id"])
    native_data = next(segment for segment in member_segments if segment["name"] == "__DATA")
    native_text = next(segment for segment in member_segments if segment["name"] == "__TEXT")
    data_command_offset = next(cursor for command, cursor, _ in member["commands"]
                               if command == 0x19 and source[cursor + 8:cursor + 24].split(b"\0", 1)[0] == b"__DATA")
    cases = []
    cases.append(("wrong_child_DATA_initprot", lambda data: struct.pack_into("<I", data, data_command_offset + 60, 7),
                  "member protection exceeds parent", "DarwinBoot.c:270-278"))
    cases.append(("wrong_absolute_DATA_fileoff", lambda data: struct.pack_into(
        "<Q", data, data_command_offset + 40, native_data["fileoff"] + 0x1000),
                  "member file backing does not match root", "DarwinBoot.c:271-274"))
    cases.append(("overlapping_member_VA", lambda data: struct.pack_into(
        "<Q", data, data_command_offset + 24, native_text["va"]), "member virtual segments overlap",
                  "DarwinBoot.c:194-199"))

    duplicate = next(row for row in entries if row["command_offset"] > entry["command_offset"] and
                     row["command_size"] - row["name_offset"] >= len(b"com.apple.kernel") + 1)
    duplicate_offset = duplicate["command_offset"] + duplicate["name_offset"]
    cases.append(("duplicate_kernel_fileset_entry", lambda data: data.__setitem__(
        slice(duplicate_offset, duplicate_offset + len(b"com.apple.kernel\0")), b"com.apple.kernel\0"),
                  "kernel entry must be unique", "DarwinBoot.c:256-258"))

    positive = subprocess.run([str(args.parser)], input=source, capture_output=True, timeout=60)
    if positive.returncode != 0:
        raise SystemExit("positive parser fixture was rejected")

    def check_fixture(name, image, expected, rejection_source):
        result = subprocess.run([str(args.parser)], input=image, capture_output=True, timeout=60)
        return {"name": name, "bytes": len(image), "sha256": sha256(image),
                "expected_rejection": expected, "parser_exit_code": result.returncode,
                "expected_source_rejection": rejection_source,
                "observed_efi_load_error": result.returncode == 1 and
                    result.stderr.strip() == b"DarwinBoot parser REJECT status=1"}

    results = []
    for name, mutate, reason, rejection_source in cases:
        changed = bytearray(source)
        mutate(changed)
        results.append(check_fixture(name, changed, reason, rejection_source))
    last_backing = max(segment["fileoff"] + segment["filesize"] for segment in root_segments if segment["filesize"])
    results.append(check_fixture("truncated_root_backing", source[:last_backing - 1],
                                 "root segment backing exceeds file", "DarwinBoot.c:176-177"))
    report = {"sample_bytes": len(source), "sample_sha256": sha256(source),
              "positive_parser_exit_code": positive.returncode, "negative_fixtures": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not all(row["observed_efi_load_error"] for row in results):
        raise SystemExit("identity or parser rejection check failed")
    print(f"PASS: production parser accepted {len(source)}-byte input without a map")
    print(f"PASS: production parser rejected {len(results)} controlled malformed samples")


if __name__ == "__main__":
    main()
