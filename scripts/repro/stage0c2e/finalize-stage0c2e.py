"""Validate the independent 2E build and publish reviewed JSON fields only."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
RULES = runpy.run_path(str(ROOT / "scripts/finalize-stage0c2a-r.py"))
PIN = json.loads(Path(__file__).with_name("stage0c2e-inputs.json").read_bytes())
OBJECTS = ("NativeUfs.late.o", "NativeRamBlock.late.o", "BootLog.o")
OBJECT_TYPES = {"bytes", "sha256", "magic", "cpu", "subtype", "filetype"}


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
                 "stage0c2a-r-parser-tests.json", "stage0c2a-r-audit-runtime.json"):
        try:
            at_root = name in ("stage0c2a-r-workflow-identity.json", "stage0c2a-r-dependencies.json")
            doc = read_json((args.temp if at_root else base) / name)
            if name == "objects.json":
                object_identity(doc)
            else:
                if name == "strict-result.json":
                    require(doc.pop("candidate_track", None) == "stage0c2e", "CANDIDATE_TRACK")
                RULES["validate"](name, doc)
            records[name] = doc
            save(name, doc)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            issue.append("MISSING_OR_INVALID/" + name)

    try:
        observed = read_json(base / "inputs.json")
        require(observed["archive_sha256"] == PIN["archive_sha256"] and observed["stage0c2e_patches"] == PIN["patches"]
                and observed["stage0c2e_sources"] == PIN["sources"], "SOURCE_PINS")
        save("stage0c2e-inputs.json", PIN)
    except (OSError, ValueError, KeyError, TypeError):
        issue.append("SOURCE_PINS")

    capture = records.get(RULES["CAPTURE"], {})
    strict = records.get("strict-result.json", {})
    tools = records.get("toolchain.json", {})
    runtime = records.get("stage0c2a-r-audit-runtime.json", {})
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
        ("NEW_IDENTITY", bool(candidate) and candidate.get("sha256") != RULES["CANDIDATE"] and
         capture.get("sample_kind") == "new-candidate"),
        ("STRICT_AND_MAP", strict.get("candidate_sha256") == candidate.get("sha256") and
         strict.get("candidate_bytes") == candidate.get("bytes") and strict.get("map_sha256") ==
         (capture.get("map") or {}).get("sha256") and strict.get("retained_entries") == 48 and
         strict.get("loadable") is False and strict.get("runtime_qualified") is False),
        ("PARSER", capture.get("parser_result") == "ACCEPT" and capture.get("parser_exit_code") == 0 and
         capture.get("parser_source_sha256") == RULES["PARSER_SOURCE"] and
         runtime.get("generated_parser_sha256") == RULES["GENERATED_C"] and
         runtime.get("compiler_sha256") == RULES["CLANG"] and
         runtime.get("parser_sha256") == capture.get("parser_executable_sha256")),
        ("STRUCTURE", RULES["segment_evidence"](capture) and len(capture.get("fileset_entries") or []) == 49),
        ("NEGATIVES", bool(tests) and tests.get("positive_parser_exit_code") == 0 and
         (tests.get("sample_bytes"), tests.get("sample_sha256")) == (candidate.get("bytes"), candidate.get("sha256")) and
         all(row["observed_efi_load_error"] and row["parser_exit_code"] == 1 and row["sha256"] != candidate.get("sha256")
             for row in tests.get("negative_fixtures", []))),
    )
    issue.extend(code for code, passed in positives if not passed)
    digests = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(args.publish.glob("*.json"))}
    status = "BLOCKED" if issue else "PASS"
    save("stage0c2e-verdict.json", dict(candidate_track="stage0c2e", status=status, issues=issue,
         build=args.build_outcome, capture=args.capture_outcome, candidate_identity=candidate,
         parser_observation=capture.get("parser_result", "NOT_RUN"), artifacts_sha256=digests))
    print("Stage 0C-2E", status, ",".join(issue))
    return 1 if issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
