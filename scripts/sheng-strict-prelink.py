#!/usr/bin/env python3
"""Revalidate real sheng bindings on a newly built native, then emit strictly.

The author engine and its original regressions are unchanged. Historical
functions must remain relocation-equivalent. Five new interfaces require
the qualified source patches and their real named definitions. No incomplete
or stubbed image is published, and the engine's runtime fields are preserved.
"""
import argparse
import bisect
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clean_prelink_recovery import (check_kit, require, read_pinned, publish,
                                    verify_bindings)

TREE = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
MASK = (1 << 64) - 1


def sha(data):
    return hashlib.sha256(data).hexdigest()


def indexed(image):
    symbols = image.symbols()
    names = {}
    for address, aliases in symbols.items():
        for name in aliases:
            names.setdefault(name, set()).add(address)
    return symbols, sorted(symbols), {name: next(iter(values)) for name, values in names.items() if len(values) == 1}


def describe(image, symbols, addresses, target):
    section = image.section(target)
    at = bisect.bisect_right(addresses, target) - 1
    if at >= 0:
        base = addresses[at]
        if image.section(base) == section and target - base < 0x10000:
            return dict(names=symbols[base], addend=target - base,
                        section=(section["segment"], section["name"]) if section else None)
    return dict(address=target, section=section)


def relocations(image):
    from fileset_layout import split_references
    result = {}
    for kind, source, offset, target, addend in split_references(image):
        source_va = (image.base if source == 0 else image.sections[source - 1]["va"]) + offset
        target_va = (image.base if target == 0 else image.sections[target - 1]["va"]) + addend
        result.setdefault(source_va, []).append((kind, target_va))
    return result


def revalidate(document, old_data, new_data):
    from kc_image import Image, scan
    from fileset_shape import checked_shape
    from m4_prelink_evidence import object_bytes
    old, new = Image(old_data), Image(new_data)
    osym, oaddrs, onames = indexed(old)
    nsym, naddrs, nnames = indexed(new)
    ostarts, nstarts = old.function_starts(), new.function_starts()
    orels, nrels = relocations(old), relocations(new)
    changes = []
    for row in document["functions"]:
        name = row["native_symbol"]
        require(name in onames and name in nnames, "Missing/ambiguous historical implementation: " + name)
        ob, nb = onames[name], nnames[name]
        require(ob in ostarts and nb in nstarts, "Historical implementation is no longer a function start: " + name)
        oe, ne = ostarts[bisect.bisect_right(ostarts, ob)], nstarts[bisect.bisect_right(nstarts, nb)]
        left, right = old.read(ob, oe - ob), new.read(nb, ne - nb)
        require(sha(left) == row["native_sha256"] and len(left) == row["native_size"], "Reviewed baseline implementation changed: " + name)
        require(len(left) == len(right) and checked_shape(left, ob)[0] == checked_shape(right, nb)[0],
                "Historical function implementation/shape changed: " + name)
        ocalls = {pc: (target, link) for pc, target, link in scan(left, ob)[0]}
        ncalls = {pc: (target, link) for pc, target, link in scan(right, nb)[0]}
        words = []
        for offset in range(0, len(left), 4):
            if left[offset:offset + 4] == right[offset:offset + 4]:
                continue
            a, b = orels.get(ob + offset), nrels.get(nb + offset)
            if not a or not b:
                x, y = ocalls.get(ob + offset), ncalls.get(nb + offset)
                require(x and y and x[1] == y[1], f"Unexplained changed instruction: {name}+{offset:#x}")
                a, b = [("BL" if x[1] else "B", x[0])], [("BL" if y[1] else "B", y[0])]
            require(len(a) == len(b), "Changed relocation multiplicity: " + name)
            evidence = []
            for (ak, av), (bk, bv) in zip(a, b):
                ad, bd = describe(old, osym, oaddrs, av), describe(new, nsym, naddrs, bv)
                common = sorted(set(ad.get("names", [])) & set(bd.get("names", [])))
                require(ak == bk and ad.get("addend") == bd.get("addend") and ad.get("section") == bd.get("section"),
                        f"Changed relocation contract: {name}+{offset:#x}")
                require(common or av == bv, f"Unproven relocation target: {name}+{offset:#x}")
                evidence.append(dict(kind=ak, old=hex(av), new=hex(bv), names=common, addend=ad.get("addend")))
            words.append(dict(offset=offset, old_word=left[offset:offset + 4].hex(), new_word=right[offset:offset + 4].hex(),
                              relocations=evidence))
        row.update(native_size=len(right), native_sha256=sha(right))
        row["evidence"] += " New candidate revalidation requires identical reviewed code shape and named relocation targets/addends."
        changes.append(dict(symbol=name, old_sha256=sha(left), new_sha256=sha(right), changed_words=words))
    for row in document["data"]:
        target = nnames[row["native_symbol"]]
        if "native_fixup" in row:
            hook = row["native_fixup"]
            require(new.fixups().get(target) == (nnames[hook["symbol"]], *hook["fields"]),
                    "Real panic handler/authentication changed")
            row["native_bytes"] = object_bytes(new, target, row["native_size"], row.get("native_zerofill", False)).hex()
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("kernel", "prelinked", "output", "fileset-reference"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--slide", required=True)
    parser.add_argument("--root", required=True, action="append")
    parser.add_argument("--early-security-init", action="append", default=[])
    args = parser.parse_args()
    require(not args.output.exists(), "Refuse to overwrite a candidate")
    attempt = Path(tempfile.mkdtemp(prefix=".sheng-evidence-", dir=args.output.parent))
    receipt = dict(started_at=datetime.now(timezone.utc).isoformat(), status="validating",
                   candidate_written=False, device_operations=False, author_engine_unchanged=True)
    try:
        contract = json.loads((SCRIPTS / "clean-prelink-contract.json").read_text())
        current = json.loads((SCRIPTS / "sheng-candidate-prelink-contract.json").read_text())
        kit = TREE / "kits/XnuPrelink"
        check_kit(kit, contract)
        read_pinned(SCRIPTS / "m4_prelink_evidence.py", contract["interface_guard_sha256"], "Historical interface guard")
        fixture = read_pinned(SCRIPTS / "clean-prelink-symbols.json", contract["reviewed_fixture_sha256"], "Historical real bindings")
        document = json.loads(fixture)
        raw = read_pinned(args.prelinked, contract["inputs"]["kernelcache"], "Original kernelcache")
        old_data = read_pinned(Path(os.environ["UNIXNU_SHENG_BASELINE_NATIVE"]), contract["inputs"]["native"], "Reviewed baseline native")
        new_data, reference_data = args.kernel.read_bytes(), args.fileset_reference.read_bytes()
        require(args.root == contract["roots"], "Candidate closure roots changed")
        early = {}
        for entry in args.early_security_init:
            owner, address = entry.split("=", 1)
            require(owner not in early, "Duplicate early initializer")
            early[owner] = int(address, 0)
        require(early == {k: int(v, 16) for k, v in contract["early_security_init"].items()}, "Early security contract changed")
        reference_receipt = json.loads(args.fileset_reference.with_suffix(".json").read_text())
        require(reference_receipt["sha256"] == sha(reference_data), "New reference build receipt differs")
        require(reference_receipt["inputs"].get("native_diagnostics") is True,
                "Reference did not select the genuine native archive diagnostics")
        diagnostics = reference_receipt.get("native_archive_diagnostics") or {}
        require(diagnostics.get("final_defined_symbols_verified") == sorted((
            "___ubsan_handle_add_overflow_minimal", "___ubsan_handle_negate_overflow_minimal",
            "___ubsan_handle_sub_overflow_minimal", "_mach_assert_jump_key")),
            "Reference lacks the final genuine diagnostic provider evidence")
        require(not diagnostics.get("synthesized_providers", True) and
                not diagnostics.get("consumer_instrumentation_disabled", True),
                "Reference diagnostic provider qualification is incomplete")
        for relative, expected in current["prepared_sources"].items():
            read_pinned(TREE / ".cache/xnu-work" / relative, expected, "Qualified prepared source " + relative)
        receipt.update(inputs=dict(native_sha256=sha(new_data), reference_sha256=sha(reference_data),
                                   kernelcache_sha256=sha(raw), baseline_native_sha256=sha(old_data)))
        stage = attempt / "prelink"
        (stage / "fixtures").mkdir(parents=True)
        for name in contract["engine"]:
            shutil.copyfile(kit / name, stage / name)
        for name in contract["engine_fixtures"]:
            shutil.copyfile(kit / "fixtures" / name, stage / "fixtures" / name)
        sys.path.insert(0, str(stage))
        from kc_image import Image, signed
        from fileset_match import match_images
        from fileset_emit import emit_images, dependency_closure, rebase_collection, atomic_write
        from fileset_layout import Layout
        from m4_prelink_evidence import validate
        receipt["historical_revalidation"] = revalidate(document, old_data, new_data)
        native = Image(new_data)
        _, _, names = indexed(native)
        original = Image(raw, Image(raw).entries["com.apple.kernel"][1])
        for row in current["new_functions"]:
            require(row["native_symbol"] in names, "Missing real new interface: " + row["native_symbol"])
            address = int(row["original"], 16)
            require(sha(original.read(address, row["original_size"])) == row["original_sha256"], "Original new-interface contract changed")
            begin = names[row["native_symbol"]]
            starts = native.function_starts()
            require(begin in starts, "New interface has no native function extent")
            end = starts[bisect.bisect_right(starts, begin)]
            require(end - begin > 8, "New interface is an empty/fixed-return entry")
            document["functions"].append(dict(row, native_size=end - begin, native_sha256=sha(native.read(begin, end - begin))))
        closure = dependency_closure(Image(raw), args.root)
        receipt["interface_guard"] = validate(document, raw, new_data, closure)
        (stage / "fixtures/fileset-24A446-sheng-candidate-symbols.json").write_text(json.dumps(document, indent=2) + "\n")
        (attempt / "qualified-symbols.json").write_text(json.dumps(document, indent=2) + "\n")
        print("Qualified historical implementations and real candidate interfaces; matching new inputs", flush=True)
        pairing = match_images(raw, new_data, reference_data=reference_data)
        atomic_write(args.output.with_suffix(".map.json"), (json.dumps(pairing, indent=2) + "\n").encode())
        image, report = emit_images(raw, new_data, pairing, args.root, early_security_init=early)
        report.update(kernelcache=str(args.prelinked.resolve()), native=str(args.kernel.resolve()),
                      map=str(args.output.with_suffix(".map.json").resolve()))
        require(not report["stubbed"] and not report["missing"], "Strict native pairing remains incomplete; see retained evidence")
        require(not report["statistics"].get("unproven_kernel_page_references", 0), "Unproven kernel page references remain")
        bindings = contract["bindings"] + current["new_bindings"]
        receipt["independent_slots"] = verify_bindings(image, raw, new_data, args.root, early, document, bindings)
        output = Image(image)
        require(output.kind == 12 and "com.apple.kernel" in output.entries, "Expected a complete native fileset")
        rebased, slide, _ = rebase_collection(Image(raw), native.base, closure, early, set(args.root))
        layout = Layout(rebased, native, closure)
        target = (int(current["normal_pal_selector"], 16) + slide) & MASK
        branch = [row for row in report["native_original_branches"] if row["symbol"] == "_sheng_image4_normal_pal"]
        require(len(branch) == 1 and int(branch[0]["target"], 16) == target, "Image4 PAL branch target mismatch")
        source = int(branch[0]["source"], 16)
        bti, word = struct.unpack("<2I", output.read(source - 4, 8))
        require(bti == 0xd503245f and word & 0xfc000000 == 0x14000000 and
                source + signed(word & 0x3ffffff, 26) * 4 == target, "Image4 BTI/B relocation did not reach real retained selector")
        receipt["normal_pal_branch"] = branch[0]
        for name, (_, at) in output.entries.items():
            member = Image(image, at)
            for segment in member.segments:
                require(segment["fileoff"] + segment["filesize"] <= len(image), name + " segment exceeds file bounds")
                if segment["size"] and segment["name"] != "__LINKEDIT":
                    require(any(s["va"] <= segment["va"] and segment["va"] + segment["size"] <= s["va"] + s["size"]
                                for s in output.segments), name + " segment exceeds root mapping")
        output.fixups()
        regression = read_pinned(Path(os.environ["UNIXNU_SHENG_REGRESSION_SOURCE"]), contract["regression_source_sha256"], "Original regression source")
        policy = read_pinned(TREE / "scripts/policies/ipados-27.0.1-24A446/prelink-regression.json",
                             contract["regression_policy_sha256"], "Original regression policy")
        publish(image, report, args.output, args.output.with_suffix(".json"), regression, json.loads(policy))
        receipt.update(status="strict_candidate_written_runtime_unqualified", candidate_written=True,
                       candidate_sha256=sha(image), recovered_import_occurrences=len(bindings),
                       source_inputs_modified=False)
        require(args.kernel.read_bytes() == new_data and args.fileset_reference.read_bytes() == reference_data,
                "Source image changed during prelink")
    except Exception as error:
        receipt.update(status="refused", error_type=type(error).__name__, error=str(error))
        if "report" in locals():
            (attempt / "kernel-report.json").write_text(json.dumps(report, indent=2) + "\n")
        raise
    finally:
        (attempt / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("Strict prelink evidence:", attempt, receipt["status"], flush=True)


if __name__ == "__main__":
    main()
