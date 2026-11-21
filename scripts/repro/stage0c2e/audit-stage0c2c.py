"""Inventory early mutation sites on identity-checked ARM64e filesets."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import runpy
import struct
import sys

PAGE = 4096
KIT_SHA = "2a2561308b27ace4e21dd4e45924bdeca937ee13047b7c6fd5ce580018f68747"
LANDING_PADS = {
    0xD503241F: "bti",
    0xD503245F: "bti c",
    0xD503249F: "bti j",
    0xD50324DF: "bti jc",
    0xD503233F: "paciasp",
    0xD503237F: "pacibsp",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def cache_fixups(image):
    data = image.data
    command = image.command(0x80000034)
    require(command is not None, "missing chained fixup command")
    off, size = struct.unpack_from("<II", data, command[0] + 8)
    end = off + size
    require(size >= 32 and end <= len(data), "chained fixup command bounds")
    _, starts = struct.unpack_from("<II", data, off)
    table = off + starts
    require(28 <= starts <= size - 4, "chained fixup table bounds")
    count, = struct.unpack_from("<I", data, table)
    require(table + 4 + count * 4 <= end, "chained fixup index bounds")
    for relative, in struct.iter_unpack("<I", data[table + 4:table + 4 + count * 4]):
        if relative == 0:
            continue
        start = table + relative
        require(table + 4 + count * 4 <= start <= end - 22, "chain starts out of range")
        bounds, step, fmt, _, _, pages = struct.unpack_from("<IHHQIH", data, start)
        require(fmt == 8, "format unsupported by this XNU ARM64 walker")
        require(step in (4096, 16384) and 22 + pages * 2 <= bounds <= end - start,
                "chain page starts out of range")
    return image.fixups()


def collect(Image, data, include_ranges=False):
    root = Image(data)
    kernel = Image(data, root.entries["com.apple.kernel"][1])
    pages = defaultdict(lambda: defaultdict(set))
    counts = Counter()
    root_segments = [(s["va"], s["va"] + s["size"],
                      struct.unpack_from("<I", data, s["command_offset"] + 60)[0], s["name"])
                     for s in root.segments if s["size"]]

    def record(kind, va, size, require_text=False):
        candidates = [(perm, name) for a, b, perm, name in root_segments if a <= va < va + size <= b]
        require(len(candidates) == 1, "early mutation outside unique root coverage")
        perm, name = candidates[0]
        if require_text:
            require(name == "__TEXT_EXEC" and perm == 5 and va % 4 == 0, "static branch not aligned RX text")
        counts[kind] += 1
        pages[kind][name].update(range(va // PAGE, (va + size - 1) // PAGE + 1))

    notes = cache_fixups(root)
    for va, (_target, auth, *_metadata) in notes.items():
        record("authenticated_fixup" if auth else "plain_fixup", va, 8)

    for image in [root, *(Image(data, off) for _, off in root.entries.values())]:
        def record_header(fileoff):
            for s in root.segments:
                delta = fileoff - s["fileoff"]
                if 0 <= delta <= s["filesize"] - 8:
                    record("load_command_slide", s["va"] + delta, 8)
                    return
            raise ValueError("load-command mutation lacks root file backing")

        for command, at, _size in image.commands:
            if command == 0x19:
                record_header(at + 24)
                total, = struct.unpack_from("<I", data, at + 64)
                for index in range(total):
                    section = at + 72 + 80 * index
                    record_header(section + 32)
                    va, length = struct.unpack_from("<QQ", data, section + 32)
                    flags, = struct.unpack_from("<I", data, section + 64)
                    if length and (flags & 0xFF) in (9, 10):
                        require(length % 8 == 0, "misaligned structor list")
                        for slot in range(va, va + length, 8):
                            if root.read(slot, 8) != bytes(8):
                                record("structor_sign", slot, 8)
            elif command == 0x80000035:
                record_header(at + 8)
        symtab = image.command(2)
        if image is root or symtab is None:
            continue
        symoff, nsyms = struct.unpack_from("<II", data, symtab[0] + 8)
        linkedit = next((s for s in image.segments if s["name"] == "__LINKEDIT"), None)
        if linkedit is not None and nsyms:
            va = linkedit["va"] + symoff - linkedit["fileoff"]
            entries = root.read(va, nsyms * 16)
            for index in range(nsyms):
                if not entries[index * 16 + 4] & 0xE0:
                    record("symbol_slide", va + index * 16 + 8, 8)

    branch_table = next(s for s in kernel.sections if s["name"] == "__static_if")
    start = branch_table["va"]
    code = next(s for s in kernel.segments if s["name"] == "__TEXT_EXEC")
    for index, (delta, target, _) in enumerate(struct.iter_unpack("<iiQ", root.read(start, branch_table["size"]))):
        slot = start + 16 * index
        record("static_if_table_link", slot + 8, 8)
        point = slot + delta
        if not code["va"] <= point < code["va"] + code["size"]:
            counts["static_if_not_in_patch_range"] += 1
            continue
        opcode, = struct.unpack("<I", root.read(point, 4))
        require(target % 4 == 0 and -(1 << 27) <= target < (1 << 27), "invalid static branch displacement")
        branch = 0x14000000 | ((target >> 2) & 0x03FFFFFF)
        require(opcode in (0xD503201F, branch), "static branch instruction is not owned by its entry")
        record("static_if_possible_text_patch", point, 4, require_text=True)

    patch_pages = pages["static_if_possible_text_patch"]["__TEXT_EXEC"]
    transition_symbols = {"_arm_init", "_arm_static_if_init", "_static_if_init", "___static_if_key_delta",
                          "_ml_static_if_entry_patch", "_ml_static_if_flush_icache", "_ExceptionVectorsBase"}
    overlaps = {name: va // PAGE in patch_pages for va, names in kernel.symbols().items()
                for name in names if name in transition_symbols}
    require(overlaps.keys() == transition_symbols, "missing early execution symbols")
    callbacks = next(s for s in kernel.sections if s["name"] == "__static_ifinit")
    require(callbacks["size"] > 0 and callbacks["size"] % 8 == 0, "early branch callback table shape")
    callback_targets = [notes[va][0] for va in range(callbacks["va"], callbacks["va"] + callbacks["size"], 8)]
    instructions = Counter()
    code_target_candidates = {target for target, auth, key, *_ in notes.values() if auth and key in (0, 1)}
    for target in code_target_candidates:
        if not any(perm & 4 and lo <= target <= hi - 4 for lo, hi, perm, _ in root_segments):
            instructions["not_executable_by_root_segment"] += 1
            continue
        opcode, = struct.unpack("<I", root.read(target, 4))
        instructions[LANDING_PADS.get(opcode, "other_first_instruction")] += 1
    report = dict(counts=dict(counts), pages_by_root_segment={tag: {name: len(used) for name, used in each.items()}
                                                          for tag, each in pages.items()},
                early_execution_symbol_on_possible_patch_page=overlaps, static_if_callback_count=len(callback_targets),
                callbacks_on_possible_patch_page=sum(va // PAGE in patch_pages for va in callback_targets),
                authenticated_instruction_key_target_count=len(code_target_candidates),
                unique_authenticated_instruction_key_target_first_insn=dict(sorted(instructions.items())))
    if include_ranges:
        base_page = min(row[0] for row in root_segments) // PAGE

        def ranges(numbers):
            spans = []
            for n in sorted(numbers):
                offset = (n - base_page) * PAGE
                if spans and offset == spans[-1][0] + spans[-1][1]:
                    spans[-1][1] += PAGE
                else:
                    spans.append([offset, PAGE])
            return spans

        report["root_base_va"] = base_page * PAGE
        report["relative_write_page_ranges"] = {
            tag: {name: ranges(used) for name, used in each.items()} for tag, each in pages.items()
        }
        report["relative_callback_entry_page_ranges"] = ranges({va // PAGE for va in callback_targets})
        report["relative_callback_patch_overlap"] = ranges({va // PAGE for va in callback_targets} & patch_pages)
        starts = kernel.function_starts()
        boundaries = dict(zip(starts, starts[1:]))
        body_pages = set()
        unresolved = 0
        for va in callback_targets:
            limit = boundaries.get(va)
            if limit is None or not any(perm & 4 and lo <= va < limit <= hi for lo, hi, perm, _ in root_segments):
                unresolved += 1
                continue
            body_pages.update(range(va // PAGE, (limit - 1) // PAGE + 1))
        report["relative_callback_function_bound_page_ranges"] = ranges(body_pages)
        report["relative_callback_function_bound_patch_overlap"] = ranges(body_pages & patch_pages)
        report["callbacks_without_function_bounds"] = unresolved
    return report


def changed_authenticated_entries(Image, before, after):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

    root = Image(before)
    later = Image(after)
    kernel = Image(before, root.entries["com.apple.kernel"][1])
    symbols = kernel.symbols()
    targets = Counter(target for target, auth, key, *_ in cache_fixups(root).values() if auth and key in (0, 1))
    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    results = []
    for target, count in sorted(targets.items()):
        old, new = root.read(target, 4), later.read(target, 4)
        if old == new:
            continue
        source = next(disassembler.disasm(old, target, count=1), None)
        destination = next(disassembler.disasm(new, target, count=1), None)
        results.append(dict(symbols=symbols.get(target, []), authenticated_references=count,
                            before=source.mnemonic if source else None, after=destination.mnemonic if destination else None))
    return results


def main():
    if sys.argv[1:2] == ["--candidate"]:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--candidate", type=Path, required=True)
        parser.add_argument("--capture", type=Path, required=True)
        parser.add_argument("--kit", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        require(sha(args.kit.read_bytes()) == KIT_SHA, "unexpected image parser")
        capture = json.loads(args.capture.read_bytes())
        data = args.candidate.read_bytes()
        require(len(data) == capture["candidate"]["bytes"] and sha(data) == capture["candidate"]["sha256"],
                "candidate bytes disagree with capture identity")
        require(capture["parser_result"] == "ACCEPT" and capture["segment_audit"] == "PASS",
                "candidate capture did not pass")
        Image = runpy.run_path(str(args.kit))["Image"]
        census = collect(Image, data, include_ranges=True)
        require(census["root_base_va"] == capture["root"]["base_va"], "capture base disagrees with image")
        doc = dict(candidate_sha256=sha(data), candidate_bytes=len(data), decoder_sha256=KIT_SHA, census=census,
                   range_unit="byte offset and length relative to kernel load base",
                   boot_physical_base="NOT_OBSERVED", dynamic_write_set="NOT_OBSERVED",
                   callback_execution_closure="NOT_PROVEN", runtime_wx="NOT_OBSERVED")
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(doc, indent=2) + "\n")
        print("PASS identity-bound static mutation census")
        return
    project, out = map(Path, sys.argv[1:3])
    work = project / "stage0c2-local-repairs"
    kit = project / "stage0c1f-evidence/pinned-kit/kc_image.py"
    require(sha(kit.read_bytes()) == KIT_SHA, "unexpected image parser")
    Image = runpy.run_path(str(kit))["Image"]
    reader = runpy.run_path(str(work / "scripts/audit-stage0c2d.py"))["read_fat_file"]
    paths = json.loads((project / "stage0c2-2a-work/results/loader-parser.json").read_bytes())
    lineage = json.loads(Path(__file__).with_name("2b-seal-lineage.json").read_bytes())
    before = Path(paths["historical_unsealed"]["path"]).read_bytes()
    after = reader(Path(paths["historical_fat_kernel"]["payload_image"]).read_bytes(),
                   "EFI/UniXNU/Payloads/kernel.macho")
    require(sha(before) == lineage["before_sha256"] and sha(after) == lineage["after_sha256"], "historical identity")
    unsealed = collect(Image, before)
    sealed = collect(Image, after)
    opcode_field = "unique_authenticated_instruction_key_target_first_insn"
    require({k: v for k, v in unsealed.items() if k != opcode_field} ==
            {k: v for k, v in sealed.items() if k != opcode_field}, "sealing changed mutation census")
    changed_entries = changed_authenticated_entries(Image, before, after)
    require(changed_entries == [dict(symbols=["_panic"], authenticated_references=32, before="pacibsp", after="b")],
            "unexpected historical authenticated entry change")
    require(not changed_authenticated_entries(Image, before, before), "unchanged executable is not a positive control")

    root = Image(before)
    off, _size = struct.unpack_from("<II", before, root.command(0x80000034)[0] + 8)
    starts, = struct.unpack_from("<I", before, off + 4)
    table = off + starts
    count, = struct.unpack_from("<I", before, table)
    relative = next(x for x, in struct.iter_unpack("<I", before[table + 4:table + 4 + 4 * count]) if x)
    corrupt = bytearray(before)
    struct.pack_into("<H", corrupt, table + relative + 6, 7)
    try:
        cache_fixups(Image(corrupt))
    except ValueError as exc:
        require(str(exc) == "format unsupported by this XNU ARM64 walker", "unexpected rejection")
    else:
        raise AssertionError("candidate with unsupported chain format accepted")

    doc = dict(scope="Run 41 historical, static pre-MMU-finalize write census", sealed_sha256=sha(after),
               unsealed_sha256=sha(before), decoder_sha256=KIT_SHA, unsupported_format_negative="PASS",
               census=sealed, actual_static_if_branch_selection="NOT_OBSERVED",
               bti_branch_classes_and_sctlr="NOT_OBSERVED", unsealed_bti_first_instruction_counts=unsealed[opcode_field],
               changed_authenticated_entries_after_payload_transform=changed_entries,
               historical_post_transform_landing_pad_integrity="BLOCKED",
               mapping_transition="BLOCKED", target_candidate="NOT_TESTED")
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
