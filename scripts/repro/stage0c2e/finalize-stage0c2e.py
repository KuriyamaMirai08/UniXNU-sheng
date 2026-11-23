"""Validate the independent 2E build and publish reviewed JSON fields only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[3]
RULES = runpy.run_path(str(ROOT / "scripts/finalize-stage0c2a-r.py"))
PIN = json.loads(Path(__file__).with_name("stage0c2e-inputs.json").read_bytes())
OBJECTS = ("NativeUfs.late.o", "NativeRamBlock.late.o", "BootLog.o")
OBJECT_TYPES = {"bytes", "sha256", "magic", "cpu", "subtype", "filetype"}
PARSER_SDK = "stage0c2e-parser-sdk.json"
RUNTIME = "stage0c2a-r-audit-runtime.json"
BASELINE_2E = "5ce6879dceec2f079fa703991b6700079060228bca199603c48f54abcef96ef6"


def parser_sdk_identity(row):
    require(set(row) == {"name", "version", "settings_sha256", "inttypes_header_sha256", "darwinboot_commit",
                         "empty_input_rejected"}, "PARSER_SDK_FIELDS")
    require(re.fullmatch(r"MacOSX(?:[0-9.]+)?\.sdk", row["name"]) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", row["version"]),
            "PARSER_SDK_VERSION")
    require(all(RULES["HEX64"].fullmatch(row[name]) for name in ("settings_sha256", "inttypes_header_sha256"))
            and row["darwinboot_commit"] == "5243c68ec332a227fe3680cd5da6d5a0e127035c"
            and row["empty_input_rejected"] is True, "PARSER_SDK_IDENTITY")


def read_json(path):
    if path.is_symlink() or not 0 < path.stat().st_size <= 2 << 20:
        raise ValueError("invalid JSON source")
    return json.loads(path.read_bytes())


def require(condition, code):
    if not condition:
        raise ValueError(code)


def object_identity(rows):
    require(set(rows) == set(OBJECTS), "OBJECT_NAMES")
    for row in rows.values():
        require(set(row) == OBJECT_TYPES, "OBJECT_FIELDS")
        require(RULES["byte_identity"]({k: row[k] for k in ("bytes", "sha256")}), "OBJECT_IDENTITY")
        require(all(type(row[k]) is int and 0 <= row[k] <= 0xffffffff
                    for k in ("magic", "cpu", "subtype", "filetype")), "OBJECT_ABI_FIELDS")
        require((row["magic"], row["cpu"], row["subtype"] & 0xffffff, row["filetype"]) ==
                (0xfeedfacf, 0x0100000c, 2, 1), "OBJECT_NOT_ARM64E")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    for step in ("build", "capture"):
        parser.add_argument(f"--{step}-outcome", choices=("success", "failure", "cancelled", "skipped"), required=True)
    args = parser.parse_args()
    args.publish.mkdir()
    base = args.temp / "stage0c1f-evidence"
    issue, records = [], {}

    def save(name, value):
        (args.publish / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    for name in ("stage0c2a-r-workflow-identity.json", "toolchain.json", "last-stage.json",
                 "objects.json", "strict-result.json", "stage0c2a-r-capture.json", "stage0c2a-r-dependencies.json",
                 "stage0c2a-r-parser-tests.json", RUNTIME, PARSER_SDK):
        try:
            at_root = name in ("stage0c2a-r-workflow-identity.json", "stage0c2a-r-dependencies.json", RUNTIME, PARSER_SDK)
            doc = read_json((args.temp if at_root else base) / name)
            if name == "objects.json":
                object_identity(doc)
            elif name == PARSER_SDK:
                parser_sdk_identity(doc)
            else:
                if name == "strict-result.json":
                    require(doc.pop("candidate_track", None) == "stage0c2d-resume", "CANDIDATE_TRACK")
                RULES["validate"](name, doc)
            records[name] = doc
            save(name, doc)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            issue.append("MISSING_OR_INVALID/" + name)

    try:
        observed = read_json(base / "inputs.json")
        require(observed["archive_sha256"] == PIN["archive_sha256"] and observed["stage0c2e_patches"] == PIN["patches"]
                and observed["stage0c2e_sources"] == PIN["sources"]
                and observed["stage0c2e_storage_builder"] == PIN["storage_builder"], "SOURCE_PINS")
        save("stage0c2e-inputs.json", PIN)
    except (OSError, ValueError, KeyError, TypeError):
        issue.append("SOURCE_PINS")

    capture = records.get(RULES["CAPTURE"], {})
    strict = records.get("strict-result.json", {})
    tools = records.get("toolchain.json", {})
    runtime = records.get(RUNTIME, {})
    dependencies = records.get("stage0c2a-r-dependencies.json", {})
    tests = records.get(RULES["TESTS"], {})
    candidate = capture.get("candidate", {})
    positives = (
        ("BUILD", args.build_outcome == "success"),
        ("CAPTURE", args.capture_outcome == "success"),
        ("TOOLCHAIN", tools.get("runner_image") in PIN["runner_images"] and
         (tools.get("apple_ld_sha256"), tools.get("compiler_sha256"), tools.get("macos_build"), tools.get("sdk")) ==
         (RULES["LD"], RULES["CLANG"], "25G332", "26.5")),
        ("RUST_TOOLCHAIN", dependencies.get("runner_image") == tools.get("runner_image") and
         dependencies.get("rust") == tools.get("rust") == "rustc 1.98.0 (88d9e12ae 2026-08-18)"),
        ("NEW_IDENTITY", bool(candidate) and candidate.get("sha256") not in {RULES["CANDIDATE"], BASELINE_2E, "e38e88b00accde4a56108d03088d11343a5f0a126df026bc4b83c134a2695275", "445f592f3bb87cd847adf6a89aca8ec15aa5e094953c0a8f64a19ec82399709b", "accf4a51323207ede22ac97adb730c7ac7ac579249b123fb8c3c6c3e82eef450", "e131c2ce8b173e95c858f04d43a4cb9e88d70e71132bfeea2b9768cbada84412"} and
         capture.get("sample_kind") == "new-candidate"),
        ("STRICT_AND_MAP", strict.get("candidate_sha256") == candidate.get("sha256") and
         strict.get("candidate_bytes") == candidate.get("bytes") and strict.get("map_sha256") ==
         (capture.get("map") or {}).get("sha256") and strict.get("retained_entries") == 48 and
         strict.get("loadable") is False and strict.get("runtime_qualified") is False),
        ("PARSER", capture.get("parser_result") == "ACCEPT" and capture.get("parser_exit_code") == 0 and
         capture.get("parser_source_sha256") == RULES["PARSER_SOURCE"] and
         runtime.get("generated_parser_sha256") == RULES["GENERATED_C"] and
         runtime.get("compiler_sha256") == RULES["CLANG"] and
         PARSER_SDK in records and
         runtime.get("parser_sha256") == capture.get("parser_executable_sha256")),
        ("STRUCTURE", RULES["segment_evidence"](capture) and len(capture.get("fileset_entries") or []) == 49),
        ("NEGATIVES", bool(tests) and tests.get("positive_parser_exit_code") == 0 and
         (tests.get("sample_bytes"), tests.get("sample_sha256")) == (candidate.get("bytes"), candidate.get("sha256")) and
         all(row["observed_efi_load_error"] and row["parser_exit_code"] == 1 and row["sha256"] != candidate.get("sha256")
             for row in tests.get("negative_fixtures", []))),
    )
    issue.extend(code for code, passed in positives if not passed)
    try:
        expected = read_json(Path(__file__).with_name("stage0c2c-inputs.json"))
        inputs = read_json(base / "stage0c2c-build-inputs.json")
        wanted = {key: expected[key] for key in (
            "ordered_patches", "patched_xnu_source_sha256", "source_commit", "source_tree", "marker_build_recipe", "seal_recipe", "storage_resume")}
        wanted["xnu_commit"] = expected["fixed_framework_soc_xnu"]["xnu"]
        objects = inputs.pop("bootstrap_objects")
        require(set(objects) == {"start.o", "static_if.o", "arm_vm_init.o"} and
                all(RULES["byte_identity"](obj) for obj in objects.values()), "BOOTSTRAP_OBJECTS")
        require(inputs == wanted, "PRODUCTION_SOURCE")
        inputs["bootstrap_objects"] = objects
        census = read_json(base / "stage0c2c-census.json")
        require((census["candidate_sha256"], census["candidate_bytes"]) ==
                (candidate["sha256"], candidate["bytes"]) and census["runtime_wx"] == "NOT_OBSERVED",
                "CENSUS_IDENTITY")
        require(bool(census["census"]["relative_write_page_ranges"]["static_if_possible_text_patch"])
                and bool(census["census"]["relative_callback_entry_page_ranges"]), "CENSUS_EMPTY")
        marker = census["panic_marker"]
        require(marker["resolved"] is True and marker["reference"] in ("direct", "fixup"), "PANIC_MARKER")
        save("stage0c2c-build-inputs.json", inputs)
        save("stage0c2c-census.json", census)
        seal = read_json(base / "stage0c2c-seal-pair.json")
        require(set(seal) == {"before_sha256", "after_sha256", "bytes", "tested_static_if_sites",
                              "source_crypto_post_hmac", "other_binary_changes", "runtime", "sealed_parser"},
                "SEALED_FIELDS")
        require(seal["before_sha256"] == candidate["sha256"] and seal["bytes"] == candidate["bytes"]
                and RULES["HEX64"].fullmatch(seal["after_sha256"]) and seal["after_sha256"] != candidate["sha256"]
                and type(seal["tested_static_if_sites"]) is int and seal["tested_static_if_sites"] > 0
                and seal["source_crypto_post_hmac"] == "MATCH" and seal["other_binary_changes"] is False
                and seal["runtime"] == "NOT_OBSERVED" and seal["sealed_parser"] == "ACCEPT", "SEALED_IDENTITY")
        save("stage0c2c-seal-pair.json", seal)
        fat = read_json(base / "stage0c3-fat.json")
        check_fat = runpy.run_path(str(Path(__file__).with_name("audit-stage0c3-fat.py")))["validate_receipt"]
        check_fat(fat, strict, seal)
        save("stage0c3-fat.json", fat)
        admission = read_json(base / "stage0c3-seed-admission.json")
        require(admission.get("static_seed_admission") == "PASS"
                and admission.get("initialization_allowed") is False
                and admission.get("device") == "NO-GO", "SEED_ADMISSION")
        save("stage0c3-seed-admission.json", admission)
        ledger_pins = read_json(Path(__file__).with_name("stage0c3-ledger-pins.json"))
        ledger_inputs = read_json(base / "stage0c3-ledger-inputs.json")
        require(ledger_inputs == ledger_pins, "LEDGER_PINS")
        save("stage0c3-ledger-inputs.json", ledger_inputs)
        for name in ("2c-rebase-pac-ownership.json", "2c-static-if-callback-closure.json", "2c-efi-excluded-ranges.json"):
            doc = read_json(base / name)
            require(doc.get("status") == "PASS", "AUDIT_2C/" + name)
            save(name, doc)
    except (OSError, ValueError, KeyError, TypeError):
        issue.append("STAGE0C2C_INPUTS_OR_CENSUS")
    digests = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(args.publish.glob("*.json"))}
    status = "BLOCKED" if issue else "PASS"
    save("stage0c2e-verdict.json", dict(candidate_track="stage0c2d-resume", status=status, issues=issue,
         build=args.build_outcome, capture=args.capture_outcome, candidate_identity=candidate,
         parser_observation=capture.get("parser_result", "NOT_RUN"), artifacts_sha256=digests))
    print("Stage 0C-2D resume-only Recovery", status, ",".join(issue))
    return 1 if issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
