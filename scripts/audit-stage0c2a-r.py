#!/usr/bin/env python3
"""Run the pinned DarwinBoot parser and independently describe one fileset."""

import argparse
import hashlib
import re
import json
import struct
import subprocess
from pathlib import Path

EXPECTED_SOURCE_SHA256 = "1d19ca1091962bd48b4154e3aae3d0ad80699f6c892a5a407dd3de0d62907fd9"
EXPECTED_1F_BYTES = 98_648_064
EXPECTED_1F_SHA256 = "0c71523a177783fd7fbfa4c5dee8b21622554b04ff3357cc518f2e7a821d315a"
EXPECTED_1F_MAP_SHA256 = "69149840908e0e6eaf2076db1ac65b983b46ad61533ba2286fd458bcb4a8a75a"
LC_SEGMENT_64 = 0x19
LC_FILESET_ENTRY = 0x80000035
CPU_TYPE_ARM64 = 0x0100000C
MH_FILESET = 0xC


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_1f(byte_count, digest):
    return (byte_count, digest) == (EXPECTED_1F_BYTES, EXPECTED_1F_SHA256)


def read_header(data, offset, owner):
    if offset < 0 or offset + 32 > len(data):
        raise ValueError(f"{owner}: truncated Mach-O header")
    magic, cpu, subtype, filetype, command_count, command_bytes, flags, reserved = struct.unpack_from("<8I", data, offset)
    if magic != 0xFEEDFACF or cpu != CPU_TYPE_ARM64:
        raise ValueError(f"{owner}: not a little-endian ARM64 64-bit Mach-O")
    command_start = offset + 32
    command_end = command_start + command_bytes
    if command_end > len(data) or command_count > 4096:
        raise ValueError(f"{owner}: load commands exceed file")
    commands = []
    entries = []
    cursor = command_start
    for index in range(command_count):
        if cursor + 8 > command_end:
            raise ValueError(f"{owner}: truncated load command {index}")
        command, size = struct.unpack_from("<II", data, cursor)
        if size < 8 or size & 7 or cursor + size > command_end:
            raise ValueError(f"{owner}: invalid load command {index}")
        commands.append((command, cursor, size))
        if command == 5:
            if size != 288 or struct.unpack_from("<II", data, cursor + 8) != (6, 68):
                raise ValueError(f"{owner}: malformed ARM64 thread-state entry")
            entries.append(struct.unpack_from("<Q", data, cursor + 272)[0])
        cursor += size
    if cursor != command_end:
        raise ValueError(f"{owner}: load command size does not match header")
    if len(entries) > 1:
        raise ValueError(f"{owner}: duplicate entry-point commands")
    return {
        "offset": offset,
        "cpu_type": cpu,
        "cpu_subtype": subtype,
        "filetype": filetype,
        "ncmds": command_count,
        "sizeofcmds": command_bytes,
        "flags": flags,
        "reserved": reserved,
        "entry": entries[0] if entries else None,
        "commands": commands,
    }


def segments_for(data, header, owner):
    result = []
    for command, cursor, size in header["commands"]:
        if command != LC_SEGMENT_64:
            continue
        if size < 72:
            raise ValueError(f"{owner}: short LC_SEGMENT_64")
        raw_name = data[cursor + 8:cursor + 24].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", errors="strict")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            raise ValueError("invalid segment identifier")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", data, cursor + 24)
        maxprot, initprot, section_count, flags = struct.unpack_from("<4I", data, cursor + 56)
        if 72 + section_count * 80 > size:
            raise ValueError(f"{owner}: section array exceeds {name}")
        if (vmsize > 256 << 20 or vmaddr + vmsize > 1 << 64 or
                filesize > vmsize or fileoff > len(data) or filesize > len(data) - fileoff):
            raise ValueError(f"{owner}: file backing exceeds image in {name}")
        result.append({
            "name": name,
            "va": vmaddr,
            "vmsize": vmsize,
            "fileoff": fileoff,
            "filesize": filesize,
            "maxprot": maxprot,
            "initprot": initprot,
            "sections": section_count,
            "flags": flags,
            "zerofill_bytes": vmsize - filesize,
            "owner": owner,
        })
    return result


def fileset_entries(data, header):
    entries = []
    for command, cursor, size in header["commands"]:
        if command != LC_FILESET_ENTRY:
            continue
        if size < 32:
            raise ValueError("short LC_FILESET_ENTRY")
        vmaddr, fileoff, entry_id_offset, reserved = struct.unpack_from("<QQII", data, cursor + 8)
        if entry_id_offset < 32 or entry_id_offset >= size:
            raise ValueError("invalid fileset entry identifier offset")
        entry_bytes, sep, _ = data[cursor + entry_id_offset:cursor + size].partition(b"\0")
        if not sep or not re.fullmatch(rb"[A-Za-z0-9_.-]{1,200}", entry_bytes):
            raise ValueError("invalid fileset entry identifier")
        entries.append({"id": entry_bytes.decode("utf-8", errors="strict"), "vmaddr": vmaddr,
                        "fileoff": fileoff, "reserved": reserved, "name_offset": entry_id_offset,
                        "command_offset": cursor,
                        "command_size": size})
    return entries


def command_table(header):
    return [{"command": command, "cmdsize": size, "offset": cursor}
            for command, cursor, size in header["commands"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--parser", type=Path, required=True)
    parser.add_argument("--parser-source", type=Path, required=True)
    parser.add_argument("--map", dest="map_path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-kind", choices=("auto", "1f-reproduction", "new-candidate", "run41-calibration"), default="auto")
    args = parser.parse_args()

    source_hash = sha256(args.parser_source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit(f"DarwinBoot source identity mismatch: {source_hash}")
    if args.candidate.stat().st_size >= 256 << 20:
        raise SystemExit("candidate exceeds parser input bound")
    data = args.candidate.read_bytes()
    candidate_hash = hashlib.sha256(data).hexdigest()
    candidate_bytes = len(data)
    identity_match = matches_1f(candidate_bytes, candidate_hash)
    if args.sample_kind == "1f-reproduction" and not identity_match:
        raise SystemExit("1F reproduction mode requires exact original length and SHA-256")
    if args.sample_kind == "run41-calibration" and identity_match:
        raise SystemExit("Run 41 calibration cannot be labelled as the original 1F candidate")

    try:
        run = subprocess.run([str(args.parser)], input=data, capture_output=True, timeout=60)
        parser_exit = run.returncode
        accepted = re.fullmatch(rb"DarwinBoot parser PASS root_segments=(\d+) span=(\d+) entry=([0-9a-f]+)\r?\n", run.stdout)
        parser_result = "ACCEPT" if parser_exit == 0 and accepted and not run.stderr else (
            "REJECT" if parser_exit in (1, 2) and run.stderr.strip() ==
            f"DarwinBoot parser REJECT status={parser_exit}".encode() else "ERROR")
    except (OSError, subprocess.TimeoutExpired):
        parser_exit, accepted, parser_result = None, None, "ERROR"
    report = {
        "schema_version": 1,
        "sample_kind": ("original-1f" if identity_match else
                        "run41-calibration" if args.sample_kind == "run41-calibration" else "new-candidate"),
        "candidate": {"bytes": candidate_bytes, "sha256": candidate_hash,
                      "matches_original_1f": identity_match},
        "parser_source_sha256": source_hash,
        "parser_executable_sha256": sha256(args.parser),
        "parser_exit_code": parser_exit,
        "parser_result": parser_result,
        "parser_summary": (dict(root_segments=int(accepted[1]), span=int(accepted[2]),
                                entry=int(accepted[3], 16)) if parser_result == "ACCEPT" else None),
        "map": None,
        "map_matches_original_1f": None,
        "root": None,
        "fileset_entries": None,
        "members": None,
        "segment_audit": "NOT_RUN",
    }
    if args.map_path and args.map_path.is_file():
        map_hash = sha256(args.map_path)
        report["map"] = {"bytes": args.map_path.stat().st_size, "sha256": map_hash}
        report["map_matches_original_1f"] = map_hash == EXPECTED_1F_MAP_SHA256
    check = "root-header"
    try:
        root_header = read_header(data, 0, "root")
        if root_header["filetype"] != MH_FILESET:
            raise ValueError("root filetype is not MH_FILESET")
        check = "root-segments"
        root_segments = segments_for(data, root_header, "root")
        mapped_root = [segment for segment in root_segments if segment["vmsize"]]
        if not mapped_root:
            raise ValueError("root has no mapped segment")
        report["root"] = {"header": {key: value for key, value in root_header.items() if key != "commands"},
                          "segments": root_segments, "load_commands": command_table(root_header),
                          "base_va": min(segment["va"] for segment in mapped_root),
                          "end_va": max(segment["va"] + segment["vmsize"] for segment in mapped_root)}
        check = "fileset-entry-table"
        entries = fileset_entries(data, root_header)
        report["fileset_entries"] = entries
        if len(entries) > 512:
            raise ValueError("fileset entry count exceeds audit bound")
        kernel_entries = [entry for entry in entries if entry["id"] == "com.apple.kernel"]
        if len({entry["id"] for entry in entries}) != len(entries):
            raise ValueError("duplicate fileset identifier")
        if len(kernel_entries) != 1:
            raise ValueError("independent audit requires exactly one com.apple.kernel entry")
        check = "member-segments"
        members = []
        report["members"] = members
        for entry in entries:
            member_header = read_header(data, entry["fileoff"], entry["id"])
            member_segments = segments_for(data, member_header, entry["id"])
            for segment in member_segments:
                segment["entry_id"] = entry["id"]
                segment["absolute_fileoff"] = segment["fileoff"]
            members.append({"entry": entry,
                            "header": {key: value for key, value in member_header.items() if key != "commands"},
                            "load_commands": command_table(member_header), "segments": member_segments})
        kernel_member = next(member for member in members if member["entry"]["id"] == "com.apple.kernel")
        check = "kernel-root-coverage"
        child_coverage = []
        for child in kernel_member["segments"]:
            if not child["vmsize"]:
                continue
            covering = []
            for parent in root_segments:
                va_inside = child["va"] >= parent["va"] and child["vmsize"] <= parent["va"] + parent["vmsize"] - child["va"]
                prot_inside = child["initprot"] & ~parent["initprot"] == 0
                file_inside = child["filesize"] == 0 or (
                    child["va"] - parent["va"] <= parent["filesize"] and
                    child["filesize"] <= parent["filesize"] - (child["va"] - parent["va"]) and
                    child["absolute_fileoff"] == parent["fileoff"] + child["va"] - parent["va"])
                if va_inside and prot_inside and file_inside:
                    covering.append(parent["name"])
            child_coverage.append({"member_segment": child["name"], "covering_root_segments": covering,
                                   "covered": bool(covering)})
        if any(not row["covered"] for row in child_coverage):
            raise ValueError("independent member-to-root coverage audit failed")
        native = next((segment for segment in kernel_member["segments"] if segment["name"] == "__DATA"), None)
        marker = next((segment for segment in kernel_member["segments"] if segment["name"] == "__PRELINK_DATA"), None)
        native_root = next((segment for segment in root_segments if segment["name"] == "__NATIVE_DATA"), None)
        root_data = next((segment for segment in root_segments if segment["name"] == "__DATA"), None)
        retained_data = [segment for member in members if member is not kernel_member
                         for segment in member["segments"] if segment["name"] == "__DATA" and segment["vmsize"]]
        page_size = 4096
        coverage = None
        if args.sample_kind != "run41-calibration":
            check = "separate-data-geometry"
            if native_root is None or root_data is None or native is None or marker is None:
                raise ValueError("candidate lacks separate-native-data roots/member marker")
            if marker["vmsize"] != 0 or marker["filesize"] != 0:
                raise ValueError("__PRELINK_DATA must be an empty marker")
            if marker["va"] != root_data["va"] or not root_data["vmsize"]:
                raise ValueError("__PRELINK_DATA marker is outside root __DATA boundaries")
            if not any(row["member_segment"] == "__DATA" and "__NATIVE_DATA" in row["covering_root_segments"]
                       and row["covered"] for row in child_coverage):
                raise ValueError("member __DATA lacks __NATIVE_DATA root coverage")
            if (native["va"], native["vmsize"], native["initprot"], native["maxprot"]) != (
                    native_root["va"], native_root["vmsize"], 3, 3) or (
                    native_root["initprot"], native_root["maxprot"], root_data["initprot"], root_data["maxprot"]) != (3, 3, 3, 3):
                raise ValueError("unexpected __DATA or __NATIVE_DATA shape or permissions")
            if any(value % page_size for value in (native["va"], native["vmsize"], marker["va"], root_data["vmsize"])):
                raise ValueError("DATA roots are not on 4 KiB page boundaries")
            retained_pages = set()
            for segment in retained_data:
                start = segment["va"]
                end = start + segment["vmsize"]
                delta = start - root_data["va"]
                if start < marker["va"] or end > root_data["va"] + root_data["vmsize"]:
                    raise ValueError("retained __DATA exceeds marker-to-root-end range")
                if segment["initprot"] & ~root_data["initprot"] or (
                        segment["filesize"] and (segment["fileoff"] != root_data["fileoff"] + delta or
                        delta + segment["filesize"] > root_data["filesize"])):
                    raise ValueError("retained __DATA exceeds root DATA permissions or file backing")
                retained_pages.update(range(start // page_size, (end - 1) // page_size + 1))
            coverage = {"page_size": page_size, "native_pages": native["vmsize"] // page_size,
                        "root_data_pages": root_data["vmsize"] // page_size,
                        "retained_data_pages": len(retained_pages),
                        "root_pages_without_retained_data": root_data["vmsize"] // page_size - len(retained_pages)}
            if identity_match and (len(entries) - 1, coverage["native_pages"]) != (48, 492):
                raise ValueError("original 1F retained-entry/native-DATA counts disagree")
        report["checks"] = {"kernel_entry_count": len(kernel_entries), "kernel_entry": kernel_entries[0],
                            "kernel_member_entry": kernel_member["header"].get("entry"),
                            "native_data": native, "native_data_root": native_root,
                            "root_data": root_data, "prelink_data_marker": marker,
                            "static_data_coverage": coverage, "retained_entry_count": len(entries) - 1,
                            "member_segment_root_coverage": child_coverage}
        report["segment_audit"] = "PASS"
    except (ValueError, KeyError, StopIteration, struct.error, IndexError) as error:
        report["segment_audit"] = "BLOCKED"
        report["segment_audit_error"] = check + "/" + type(error).__name__

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["parser_result"] != "ACCEPT":
        raise SystemExit(1)
    if report["segment_audit"] != "PASS":
        raise SystemExit("independent segment audit is BLOCKED: " + report.get("segment_audit_error", "unknown error"))


if __name__ == "__main__":
    main()
