#!/usr/bin/env python3
"""Validate and publish only Stage 0C-2A-R receipts, then return the job verdict."""
import argparse
import hashlib
import json
import re
from pathlib import Path

CANDIDATE = "0c71523a177783fd7fbfa4c5dee8b21622554b04ff3357cc518f2e7a821d315a"
MAP = "69149840908e0e6eaf2076db1ac65b983b46ad61533ba2286fd458bcb4a8a75a"
SIZE = 98_648_064
PARSER_SOURCE = "1d19ca1091962bd48b4154e3aae3d0ad80699f6c892a5a407dd3de0d62907fd9"
GENERATED_C = "68556301872a04446b74359361870439c99ee8e78a920b9daa8cd513bb8796db"
LD = "e412b9f2af31b1567a9eabc28f553a8f1cf34127e2107cb39c2694cf147571a4"
CLANG = "d2e4bf622758eee1bf7267c060497fb2c41e098d37b0fca8be73898dc7e14eda"
INPUTS = {
    "native_sha256": "401606296ad98c8bbad5878dc3cd97fc199c34360e2cae6973e1b1a8af2c7a08",
    "reference_sha256": "c834def8182e00e19fdfd95b223f7eb8188f36ab73d85990fd7e535f0c41ae1d",
    "kernelcache_sha256": "38e6d9fa5f789b8228f4617ef4c6d2a3fd8ab564abdc9b62920f1db53fc1780a",
    "baseline_native_sha256": "2d1071d451f27bcd330a688a2579bd789b9c5795b1d5e670239850629ec665d9",
}
PINNED_RECEIPTS = {
    "fixed-bottles.json": "a7f49031382dd91638ca4dd8fe93af5d305621666be262ec35efb127114ae8b2",
    "inputs.json": "0143b47543a179386cff3dccfd94e04a8e4d254a6b0164863a01369eea750743",
    "objects.json": "debc9b4a41991206725a4ba9ad96221c1ecdd25151905fbd7c61abd547a91cb2",
}
NEGATIVES = {
    "wrong_child_DATA_initprot", "wrong_absolute_DATA_fileoff", "overlapping_member_VA",
    "duplicate_kernel_fileset_entry", "truncated_root_backing",
}
FIXED_FIELDS = {
    "fixed-bottles.json": "z3 llvm lld",
    "inputs.json": ("archive_sha256 native.macho kernel.py patches commits framework_regression_policy_sha256 "
                    "source_helper_sha256 patched_sources kernelcache_sha256"),
    "objects.json": "NativeUfs.late.o NativeRamBlock.late.o BootLog.o",
}
OPTIONAL = {"stage0c2a-r-capture.json": {"checks", "segment_audit_error"}}
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
CAPTURE = "stage0c2a-r-capture.json"
TESTS = "stage0c2a-r-parser-tests.json"
VERDICT = "stage0c2a-r-verdict.json"


def fields(names, spec):
    return dict.fromkeys(names.split(), spec)


HASH = HEX64
UINT = int
SEGMENT_NAME = re.compile(r"[A-Za-z0-9_]{1,16}")
ENTRY_ID = re.compile(r"[A-Za-z0-9_.-]{1,200}")
HEX_ADDRESS = re.compile(r"0x[a-f0-9]{1,16}")
ENTRY = {"id": ENTRY_ID, **fields("vmaddr fileoff reserved name_offset command_offset command_size", UINT)}
SEGMENT = {"name": SEGMENT_NAME, "owner": ENTRY_ID, **fields(
    "va vmsize fileoff filesize maxprot initprot sections flags zerofill_bytes", UINT)}
MEMBER_SEGMENT = {**SEGMENT, "entry_id": ENTRY_ID, "absolute_fileoff": UINT}
HEADER = {**fields("offset cpu_type cpu_subtype filetype ncmds sizeofcmds flags reserved", UINT),
          "entry": (UINT, type(None))}
COMMAND = fields("command cmdsize offset", UINT)
SUMMARY = fields("root_segments span entry", UINT)
LAYOUT = fields("page_size native_pages root_data_pages retained_data_pages root_pages_without_retained_data", UINT)
DETAILS = {
    "kernel_entry_count": UINT, "kernel_entry": ENTRY, "kernel_member_entry": (UINT, type(None)),
    "native_data": (MEMBER_SEGMENT, type(None)), "native_data_root": (SEGMENT, type(None)),
    "root_data": (SEGMENT, type(None)), "prelink_data_marker": (MEMBER_SEGMENT, type(None)),
    "static_data_coverage": (LAYOUT, type(None)), "retained_entry_count": UINT,
    "member_segment_root_coverage": [{"member_segment": SEGMENT_NAME, "covering_root_segments": [SEGMENT_NAME],
                                       "covered": bool}],
}
ROOT = {"header": HEADER, "segments": [SEGMENT], "load_commands": [COMMAND], "base_va": UINT, "end_va": UINT}
MEMBER = {"entry": ENTRY, "header": HEADER, "segments": [MEMBER_SEGMENT], "load_commands": [COMMAND]}
BREW_NAMES = ("dtc cmake mtools ninja glslang shaderc spirv-tools spirv-headers bison pkgconf rustup "
              "blacktop/tap/ipsw zstd zlib-ng-compat")
VERSION = re.compile(r"[0-9][0-9A-Za-z._+-]{0,47}")
TYPED = {
    "stage0c2a-r-workflow-identity.json": {
        **fields("workflow_ref", str), **fields("workflow_sha fixed_source_commit fixed_source_tree", re.compile(r"[a-f0-9]{40}")),
        "workflow_sha256": HASH, "run_id": re.compile(r"[0-9]+"), "attempt": re.compile("1"),
        "audit_tool_hashes": fields("scripts/audit-stage0c2a-r.py scripts/build-darwinboot-parser.py "
                                    "scripts/finalize-stage0c2a-r.py scripts/test-stage0c2a-r.py", HASH)},
    "toolchain.json": {**fields("xcode clang sdk linker rust macos macos_build runner_image llvm lld", str),
                       **fields("compiler_sha256 apple_ld_sha256", HASH)},
    "last-stage.json": {"stage": re.compile(r"[a-zA-Z0-9_-]+"), "exit_code": "signed",
                        "log_sha256": HASH, **fields("log_bytes diagnostic_lines", UINT)},
    "optional-provider-check.json": {
        **fields("actual_gpu_consumer_sha256 actual_ram_consumer_sha256", HASH),
        **fields("actual_statement_blocks_exercised absent_and_present_host_cases_passed "
                 "missing_real_provider_negative_refused kernel_or_reference_harness_inputs device_operations", bool),
        "apple_arm64e_links": [{"mode": re.compile(r"absent|present"), "sha256": HASH,
                               **fields("imports_and_binds_refused_by_unchanged_parser provider_defined", bool)}]},
    "native.json": {"sha256": HASH, "bytes": UINT, "segments": (SEGMENT_NAME, fields("va vmsize", HEX_ADDRESS), "map")},
    "strict-result.json": {"status": re.compile(r"strict_candidate_written_runtime_unqualified"),
                           "inputs": dict.fromkeys(INPUTS, HASH),
                           **fields("candidate_sha256 map_sha256 corecrypto_hmac_sha256", HASH),
                           "placement": re.compile("separate-native-data"), "retained_entries": UINT,
                           **fields("runtime_qualified loadable", bool), "candidate_bytes": UINT,
                           "segment_layout": (SEGMENT_NAME, fields("old new size", HEX_ADDRESS), "map")},
    CAPTURE: {
        "schema_version": UINT, "sample_kind": re.compile(r"original-1f|new-candidate|run41-calibration"),
        "candidate": {"bytes": UINT, "sha256": HASH, "matches_original_1f": bool},
        **fields("parser_source_sha256 parser_executable_sha256", HASH),
        "parser_exit_code": ("signed", type(None)), "parser_result": re.compile(r"ACCEPT|REJECT|ERROR"),
        "parser_summary": (SUMMARY, type(None)), "map": ({"bytes": UINT, "sha256": HASH}, type(None)),
        "map_matches_original_1f": (bool, type(None)), "root": (ROOT, type(None)),
        "fileset_entries": ([ENTRY], type(None)), "members": ([MEMBER], type(None)),
        "segment_audit": re.compile(r"PASS|BLOCKED"), "checks": DETAILS,
        "segment_audit_error": re.compile(r"[a-z-]+/[A-Za-z]+")},
    TESTS: {"sample_bytes": UINT, "sample_sha256": HASH, "positive_parser_exit_code": UINT,
            "negative_fixtures": [{"name": re.compile("|".join(sorted(NEGATIVES))), "bytes": UINT, "sha256": HASH,
                                   "expected_rejection": str, "parser_exit_code": "signed",
                                   "expected_source_rejection": re.compile(r"DarwinBoot[.]c:[0-9]+-[0-9]+"),
                                   "observed_efi_load_error": bool}]},
    "stage0c2a-r-audit-runtime.json": {**fields("generated_parser_sha256 compiler_sha256 parser_sha256", HASH),
                                      "host_machine": re.compile("arm64")},
    "stage0c2a-r-dependencies.json": {"runner_image": VERSION, "python": VERSION, "rust": str,
                                     "brew_versions": fields(BREW_NAMES, VERSION),
                                     "pip_versions": fields("cryptography cffi pycparser", VERSION)},
}


def matches(value, spec):
    if spec is UINT:
        return type(value) is int and 0 <= value < 1 << 64
    if spec == "signed":
        return type(value) is int and -(1 << 31) <= value < 1 << 31
    if isinstance(spec, type):
        return type(value) is spec
    if isinstance(spec, re.Pattern):
        return type(value) is str and spec.fullmatch(value) is not None
    if isinstance(spec, dict):
        return isinstance(value, dict) and value.keys() == spec.keys() and all(
            matches(item, spec[key]) for key, item in value.items())
    if isinstance(spec, list):
        return isinstance(value, list) and all(matches(item, spec[0]) for item in value)
    if len(spec) == 3 and spec[-1] == "map":
        return isinstance(value, dict) and bool(value) and all(
            matches(key, spec[0]) and matches(item, spec[1]) for key, item in value.items())
    return any(matches(value, kind) for kind in spec)


def complete_command_table(image):
    header, commands = image["header"], image["load_commands"]
    start = header["offset"] + 32
    cursor = start
    for row in commands:
        if row["offset"] != cursor or row["cmdsize"] < 8 or row["cmdsize"] % 8:
            return False
        cursor += row["cmdsize"]
    return (len(commands) == header["ncmds"] and cursor - start == header["sizeofcmds"]
            and sum(row["command"] == 0x19 for row in commands) == len(image["segments"]))


def segment_evidence(capture):
    if capture.get("segment_audit") != "PASS":
        return False
    root, entries, members = (capture[key] for key in ("root", "fileset_entries", "members"))
    if not root or not entries or not members or len(entries) != len(members):
        return False
    if not complete_command_table(root) or any(not complete_command_table(m) for m in members):
        return False
    entry_commands = {(cmd["offset"], cmd["cmdsize"]) for cmd in root["load_commands"] if cmd["command"] == 0x80000035}
    if len(entry_commands) != len(entries) or entry_commands != {
            (entry["command_offset"], entry["command_size"]) for entry in entries}:
        return False
    indexed = {entry["id"]: entry for entry in entries}
    mapped = {member["entry"]["id"]: member for member in members}
    if len(indexed) != len(entries) or len(mapped) != len(members) or indexed.keys() != mapped.keys():
        return False
    if any(member["entry"] != indexed[name] or member["header"]["offset"] != indexed[name]["fileoff"]
           or not member["segments"] or any(seg["entry_id"] != name or seg["owner"] != name
           for seg in member["segments"]) for name, member in mapped.items()):
        return False
    kernel = mapped.get("com.apple.kernel")
    segments = [seg for seg in root["segments"] if seg["vmsize"]]
    if not kernel or not segments:
        return False
    entry = root["header"]["entry"]
    low = min(seg["va"] for seg in segments)
    high = max(seg["va"] + seg["vmsize"] for seg in segments)
    if (entry is None or entry != kernel["header"]["entry"] or root["header"]["filetype"] != 12
        or (low, high) != (root["base_va"], root["end_va"])
        or not any(seg["initprot"] & 4 and seg["va"] <= entry < seg["va"] + seg["filesize"] for seg in segments)):
        return False
    if any(not any(0 <= child["fileoff"] - seg["fileoff"] <= seg["filesize"] - 32
                   and child["vmaddr"] == seg["va"] + child["fileoff"] - seg["fileoff"]
                   for seg in segments) for child in entries):
        return False
    if capture["parser_result"] == "ACCEPT" and capture["parser_summary"] != {
            "entry": entry, "span": high - low, "root_segments": len(segments)}:
        return False

    # Recompute the 1F checks from the captured tables, not the claimed counts.
    if capture["sample_kind"] != "original-1f":
        return True
    native = [seg for seg in kernel["segments"] if seg["name"] == "__DATA"]
    native_root = [seg for seg in segments if seg["name"] == "__NATIVE_DATA"]
    if len(entries) != 49 or len(native) != 1 or len(native_root) != 1:
        return False
    child, parent = native[0], native_root[0]
    return ((child["va"], child["vmsize"], child["absolute_fileoff"], child["maxprot"], child["initprot"]) ==
            (parent["va"], parent["vmsize"], parent["fileoff"], 3, 3)
            and parent["maxprot"] == parent["initprot"] == 3 and parent["vmsize"] == 492 * 4096)


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def bound_metadata(item, depth=0):
    if depth > 12:
        raise ValueError("metadata nesting exceeds limit")
    if isinstance(item, dict):
        for key, value in item.items():
            if not re.fullmatch(r"[A-Za-z0-9_./@+-]{1,200}", key):
                raise ValueError("invalid metadata field")
            bound_metadata(value, depth + 1)
    elif isinstance(item, list):
        if len(item) > 4096:
            raise ValueError("metadata array exceeds limit")
        for value in item:
            bound_metadata(value, depth + 1)
    elif isinstance(item, str):
        if not re.fullmatch(r"[\x20-\x7e\r\n\t]{0,1600}", item):
            raise ValueError("invalid metadata text")
    elif item is not None and type(item) not in (bool, int):
        raise ValueError("invalid metadata type")


def byte_identity(obj):
    return (isinstance(obj, dict) and set(obj) == {"bytes", "sha256"} and
            type(obj["bytes"]) is int and obj["bytes"] > 0 and
            isinstance(obj["sha256"], str) and HEX64.fullmatch(obj["sha256"]) is not None)


def validate(name, doc):
    fields = set(FIXED_FIELDS[name].split()) if name in FIXED_FIELDS else TYPED[name].keys() - OPTIONAL.get(name, set())
    if not isinstance(doc, dict) or not fields <= doc.keys() <= (fields | OPTIONAL.get(name, set())):
        raise ValueError("missing or unknown receipt fields")
    bound_metadata(doc)
    if name in TYPED and any(not matches(value, TYPED[name][key]) for key, value in doc.items()):
        raise ValueError("unexpected receipt value or nested field")
    if name == CAPTURE:
        candidate = doc["candidate"]
        if not isinstance(candidate, dict) or set(candidate) != {"bytes", "sha256", "matches_original_1f"}:
            raise ValueError("invalid candidate identity")
        if not byte_identity({k: candidate[k] for k in ("bytes", "sha256")}):
            raise ValueError("invalid candidate bytes/hash")
        if doc["map"] is not None and not byte_identity(doc["map"]):
            raise ValueError("invalid map identity")
        if doc["parser_result"] not in ("ACCEPT", "REJECT", "ERROR") or doc["segment_audit"] not in ("PASS", "BLOCKED"):
            raise ValueError("unknown parser/segment result")
        if doc["segment_audit"] == "PASS" and not (
            isinstance(doc.get("checks"), dict) and isinstance(doc["root"], dict) and
            isinstance(doc["members"], list) and isinstance(doc["fileset_entries"], list)
        ):
            raise ValueError("missing independent segment evidence")
    if name == TESTS:
        rows = doc["negative_fixtures"]
        if not isinstance(rows, list) or len(rows) != len(NEGATIVES):
            raise ValueError("missing or extra negative fixtures")
        fields = {"name", "bytes", "sha256", "expected_rejection", "parser_exit_code",
                  "expected_source_rejection", "observed_efi_load_error"}
        if any(not isinstance(row, dict) or set(row) != fields or
               not byte_identity({k: row[k] for k in ("bytes", "sha256")}) for row in rows):
            raise ValueError("invalid negative fixture")
        if {row["name"] for row in rows} != NEGATIVES:
            raise ValueError("unexpected negative fixture names")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    parser.add_argument("--build-outcome", choices=("success", "failure", "cancelled", "skipped"), required=True)
    parser.add_argument("--capture-outcome", choices=("success", "failure", "cancelled", "skipped"), required=True)
    args = parser.parse_args()
    args.publish.mkdir()
    records, digests, issues, rejected = {}, {}, [], {}
    for name in (*FIXED_FIELDS, *TYPED):
        folder = ("stage0c1f-supply" if name == "fixed-bottles.json" else
                  "" if name.endswith(("workflow-identity.json", "dependencies.json")) else "stage0c1f-evidence")
        source = args.temp / folder / name
        try:
            if source.is_symlink() or not 0 < source.stat().st_size <= (2 << 20):
                raise ValueError("unbounded or redirected receipt")
            body = source.read_bytes()
            actual = hashlib.sha256(body).hexdigest()
            wanted = PINNED_RECEIPTS.get(name)
            if wanted is not None and actual != wanted:
                rejected[name] = {"reason": "SHA256_MISMATCH", "expected_sha256": wanted, "actual_sha256": actual}
                raise ValueError("fixed receipt checksum mismatch")
            doc = json.loads(body)
            validate(name, doc)
            if wanted is not None:
                (args.publish / name).write_bytes(body)
            else:
                write(args.publish / name, doc)
            records[name] = doc
            digests[name] = actual
        except (OSError, ValueError, TypeError, KeyError):
            issues.append("MISSING_OR_INVALID/" + name)

    capture = records.get(CAPTURE, {})
    candidate = capture.get("candidate", {})
    map_record = capture.get("map") or {}
    strict = records.get("strict-result.json", {})
    negative = records.get(TESTS, {})
    runtime = records.get("stage0c2a-r-audit-runtime.json", {})
    tools = records.get("toolchain.json", {})
    identity = (candidate.get("bytes"), candidate.get("sha256")) == (SIZE, CANDIDATE)
    parser_accepts = (capture.get("parser_result") == "ACCEPT" and capture.get("parser_exit_code") == 0 and
                      capture.get("parser_source_sha256") == PARSER_SOURCE and
                      isinstance(capture.get("parser_summary"), dict) and
                      runtime.get("generated_parser_sha256") == GENERATED_C and
                      runtime.get("host_machine") == "arm64" and runtime.get("compiler_sha256") == CLANG and
                      isinstance(runtime.get("parser_sha256"), str) and
                      HEX64.fullmatch(runtime["parser_sha256"]) is not None and
                      runtime["parser_sha256"] == capture.get("parser_executable_sha256"))
    segments_ok = segment_evidence(capture)
    result = {
        "build_outcome": args.build_outcome,
        "capture_outcome": args.capture_outcome,
        "original_1f_identity_reproduced": identity,
        "parser_observation": capture.get("parser_result", "NOT_RUN"),
        "original_1f_parser_acceptance": "PASS" if identity and parser_accepts else "BLOCKED",
        "new_candidate_parser_acceptance": "PASS" if candidate and not identity and parser_accepts else "BLOCKED",
        "segment_audit": ("PASS" if segments_ok else "BLOCKED" if capture else "NOT_RUN"),
        "original_map_match": map_record.get("sha256") == MAP,
        "negative_tests": ("PASS" if negative and
                           (negative.get("sample_bytes"), negative.get("sample_sha256")) ==
                           (candidate.get("bytes"), candidate.get("sha256")) and
                           negative.get("positive_parser_exit_code") == 0 and
                           all(row["observed_efi_load_error"] is True and row["parser_exit_code"] == 1
                               and row["sha256"] != candidate.get("sha256") for row in negative["negative_fixtures"])
                           else "BLOCKED" if negative else "NOT_RUN"),
    }
    checks = {
        "BUILD": args.build_outcome == "success",
        "CAPTURE": args.capture_outcome == "success",
        "ORIGINAL_BYTES": identity and candidate.get("matches_original_1f") is True,
        "STRICT_RECEIPT": strict.get("status") == "strict_candidate_written_runtime_unqualified" and
            strict.get("placement") == "separate-native-data" and strict.get("retained_entries") == 48 and
            strict.get("runtime_qualified") is False and strict.get("loadable") is False and
            bool(candidate and map_record) and
            (strict.get("candidate_sha256"), strict.get("candidate_bytes"), strict.get("map_sha256")) ==
            (candidate.get("sha256"), candidate.get("bytes"), map_record.get("sha256")),
        "HISTORICAL_INPUTS": strict.get("inputs") == INPUTS,
        "HISTORICAL_MAP": result["original_map_match"],
        "APPLE_TOOLCHAIN": (tools.get("apple_ld_sha256"), tools.get("compiler_sha256"),
                            tools.get("runner_image"), tools.get("macos_build"), tools.get("sdk")) ==
                           (LD, CLANG, "20261117.0516.1", "25G332", "26.5"),
        "PARSER": parser_accepts,
        "SEGMENTS": segments_ok and capture.get("sample_kind") == "original-1f",
        "NEGATIVES": result["negative_tests"] == "PASS",
        **{name: digests.get(name) == wanted for name, wanted in PINNED_RECEIPTS.items()},
    }
    result["rejected_receipts"] = rejected
    result["checks"] = checks
    result["issues"] = issues + [key for key, ok in checks.items() if not ok]
    result["status"] = "BLOCKED" if result["issues"] else "PASS"
    result["artifact_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(args.publish.glob("*.json"))}
    write(args.publish / VERDICT, result)
    print("Stage 0C-2A-R " + result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
