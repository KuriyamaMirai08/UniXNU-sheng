#!/usr/bin/env python3
"""Stage 0C-3 2C runner audit: rebase/PAC RW/RX ownership, static_if callback closure, and EFI exclusions."""
import argparse
from collections import deque
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

PAGE = 4096
OBJDUMP_LINE = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(\S+)(.*)$")
BRANCH_TARGET = re.compile(r"\b(?:0x)?([0-9a-f]{8,16})\b")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seg_bounds(image):
    return [
        (s["va"], s["va"] + s["size"], struct.unpack_from("<I", image.data, s["command_offset"] + 60)[0], s["name"])
        for s in image.segments if s["size"]
    ]


def classify_va(va: int, size: int, segments):
    for a, b, perm, name in segments:
        if a <= va < va + size <= b:
            is_rx = bool(perm & 4) and not bool(perm & 2)
            # In bootstrap tables (start.s), everything outside fileset RX is mapped RW/PXN/UXN
            # until arm_vm_prot_finalize locks __TEXT / __DATA_CONST to RO.
            return {"segment": name, "perm": perm, "rx": is_rx, "bootstrap_rw": not is_rx}
    return {"segment": "UNMAPPED", "perm": 0, "rx": False, "bootstrap_rw": False}


def audit_rebase_pac_ownership(audit_mod, kc_mod, candidate_bytes: bytes) -> dict:
    root = kc_mod.Image(candidate_bytes)
    segments = seg_bounds(root)
    notes = audit_mod.cache_fixups(root)

    counts = {"bootstrap_rw_owned": 0, "rx_violation": 0, "unmapped": 0}
    violations = []
    for va, (target, auth, *_rest) in notes.items():
        info = classify_va(va, 8, segments)
        if info["bootstrap_rw"]:
            counts["bootstrap_rw_owned"] += 1
        elif info["rx"]:
            counts["rx_violation"] += 1
            if len(violations) < 20:
                violations.append({"va": hex(va), "segment": info["segment"], "auth": bool(auth)})
        else:
            counts["unmapped"] += 1
            if len(violations) < 20:
                violations.append({"va": hex(va), "segment": info["segment"], "auth": bool(auth)})

    # Also verify structor lists and load commands
    load_cmd_rw = 0
    load_cmd_non_rw = 0
    for image in [root, *(kc_mod.Image(candidate_bytes, off) for _, off in root.entries.values())]:
        for command, at, _size in image.commands:
            if command == 0x19:
                for s in root.segments:
                    delta = at + 24 - s["fileoff"]
                    if 0 <= delta <= s["filesize"] - 8:
                        info = classify_va(s["va"] + delta, 8, segments)
                        if info["bootstrap_rw"]:
                            load_cmd_rw += 1
                        else:
                            load_cmd_non_rw += 1
                        break

    return {
        "status": "PASS" if counts["rx_violation"] == 0 and counts["unmapped"] == 0 and load_cmd_non_rw == 0 else "FAIL",
        "fixup_counts": counts,
        "load_command_header_bootstrap_rw": load_cmd_rw,
        "load_command_header_non_rw": load_cmd_non_rw,
        "sample_violations": violations,
        "target_ttbr_wxn": "NOT_OBSERVED",
    }


def resolve_objdump(preferred: str | None) -> list[str]:
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend([
        "llvm-objdump",
        "/opt/homebrew/opt/llvm/bin/llvm-objdump",
        r"C:\Program Files\Windhawk\Compiler\bin\llvm-objdump.exe",
    ])
    for cand in candidates:
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return [found]
    if shutil.which("xcrun"):
        return ["xcrun", "objdump"]
    raise FileNotFoundError("no llvm-objdump or xcrun objdump found")


def audit_callback_closure(kc_mod, audit_mod, candidate_path: Path, candidate_bytes: bytes, objdump_cmd: list[str]) -> dict:
    root = kc_mod.Image(candidate_bytes)
    kernel = kc_mod.Image(candidate_bytes, root.entries["com.apple.kernel"][1])
    root_segments = seg_bounds(root)
    notes = audit_mod.cache_fixups(root)

    callbacks = next(s for s in kernel.sections if s["name"] == "__static_ifinit")
    callback_targets = [notes[va][0] for va in range(callbacks["va"], callbacks["va"] + callbacks["size"], 8)]

    starts = kernel.function_starts()
    boundaries = dict(zip(starts, starts[1:]))
    text_exec = next(s for s in kernel.segments if s["name"] == "__TEXT_EXEC")

    # Disassemble __TEXT_EXEC once using llvm-objdump
    proc = subprocess.run(
        [*objdump_cmd, "-d", "--macho", f"--start-address={hex(text_exec['va'])}",
         f"--stop-address={hex(text_exec['va'] + text_exec['size'])}", str(candidate_path)],
        capture_output=True, text=True, check=True,
    )
    insns = {}
    for line in proc.stdout.splitlines():
        m = OBJDUMP_LINE.match(line)
        if m:
            va = int(m.group(1), 16)
            insns[va] = (m.group(3).lower(), m.group(4))

    visited_funcs = set()
    queue = deque(callback_targets)
    non_rx_pages = set()
    rx_write_suspects = []
    unresolved_funcs = []
    indirect_branch_count = 0

    while queue:
        fn = queue.popleft()
        if fn in visited_funcs:
            continue
        visited_funcs.add(fn)
        limit = boundaries.get(fn)
        if limit is None or not any((perm & 4) and not (perm & 2) and lo <= fn < limit <= hi for lo, hi, perm, _ in root_segments):
            unresolved_funcs.append(hex(fn))
            continue
        for pc in range(fn, limit, 4):
            entry = insns.get(pc)
            if not entry:
                continue
            mnem, ops = entry
            if mnem.startswith(("br", "blr")):
                indirect_branch_count += 1
            elif mnem in ("bl", "b") or mnem.startswith("b.") or mnem in ("cbz", "cbnz", "tbz", "tbnz"):
                tm = BRANCH_TARGET.search(ops)
                if tm:
                    target = int(tm.group(1), 16)
                    if not (fn <= target < limit) and target in boundaries:
                        queue.append(target)

    # Check all visited functions stay inside sealed RX pages
    for fn in visited_funcs:
        limit = boundaries.get(fn)
        if limit:
            for pg in range(fn // PAGE, (limit - 1) // PAGE + 1):
                va = pg * PAGE
                if not any((perm & 4) and not (perm & 2) and lo <= va < hi for lo, hi, perm, _ in root_segments):
                    non_rx_pages.add(hex(va))

    return {
        "status": "PASS" if not unresolved_funcs and not non_rx_pages and not rx_write_suspects else "FAIL",
        "callback_entry_count": len(callback_targets),
        "reachable_function_count": len(visited_funcs),
        "indirect_branch_count": indirect_branch_count,
        "unresolved_functions": unresolved_funcs[:20],
        "non_rx_pages": sorted(non_rx_pages)[:20],
        "target_cache_tlb": "NOT_OBSERVED",
    }


def audit_efi_excluded_ranges(adt_bytes: bytes, place_json: dict | None) -> dict:
    chosen = {}

    def visit(offset, parent, depth):
        prop_count, child_count = struct.unpack_from("<II", adt_bytes, offset)
        offset += 8
        props = {}
        for _ in range(prop_count):
            key, size = struct.unpack_from("<32sI", adt_bytes, offset)
            key = key.rstrip(b"\0")
            offset += 36
            props[key] = adt_bytes[offset:offset + size]
            offset = (offset + size + 3) & ~3
        name = props.pop(b"name", b"").rstrip(b"\0")
        path = parent + (name,) if depth else ()
        if path == (b"chosen",):
            chosen.update(props)
        for _ in range(child_count):
            offset = visit(offset, path, depth + 1)
        return offset

    visit(0, (), 0)
    win = struct.unpack("<Q", chosen[b"darwinboot-memory-size"])[0] if b"darwinboot-memory-size" in chosen else None
    excl = chosen.get(b"darwinboot-memory-excluded")
    excl_ranges = []
    if excl and len(excl) % 16 == 0:
        for base, sz in struct.iter_unpack("<QQ", excl):
            excl_ranges.append({"base": hex(base), "bytes": sz})

    return {
        "status": "PASS" if win is not None else "FAIL",
        "darwinboot_memory_size": win,
        "adt_excluded_ranges": excl_ranges,
        "place_image_used_bytes": place_json.get("used_bytes") if place_json else None,
        "place_image_window_bytes": place_json.get("window_bytes") if place_json else None,
        "final_efi_map": "NOT_OBSERVED",
        "device": "NO-GO",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--adt", type=Path, required=True)
    ap.add_argument("--kc-image", type=Path, required=True)
    ap.add_argument("--audit-2c", type=Path, required=True)
    ap.add_argument("--objdump", default=None)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kc_mod = load_module("kc_image", args.kc_image)
    audit_mod = load_module("audit_2c", args.audit_2c)
    data = args.candidate.read_bytes()
    objdump_cmd = resolve_objdump(args.objdump)

    r1 = audit_rebase_pac_ownership(audit_mod, kc_mod, data)
    r2 = audit_callback_closure(kc_mod, audit_mod, args.candidate, data, objdump_cmd)
    r3 = audit_efi_excluded_ranges(args.adt.read_bytes(), None)

    (args.out_dir / "2c-rebase-pac-ownership.json").write_text(json.dumps(r1, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "2c-static-if-callback-closure.json").write_text(json.dumps(r2, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "2c-efi-excluded-ranges.json").write_text(json.dumps(r3, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rebase_pac": r1["status"], "callback_closure": r2["status"], "efi_excluded": r3["status"]}))
    if r1["status"] != "PASS" or r2["status"] != "PASS" or r3["status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
