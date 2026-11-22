"""Independently verify the permitted byte changes of final fileset pre-sealing."""
import hashlib
import hmac
import json
from pathlib import Path
import runpy
import struct
import sys

HERE = Path(__file__).resolve().parent


def require(value, error):
    if not value:
        raise ValueError(error)


def verify(Image, before, after):
    require(len(before) == len(after), "sealed size changed")
    root = Image(before)
    member = Image(before, root.entries["com.apple.kernel"][1])
    chain = root.fixups()
    authenticated_entries = {target for target, auth, key, *_ in chain.values() if auth and key in (0, 1)}
    names = {"_static_if_test_key_true_to_false_jump_key", "_static_if_test_key_false_to_true_jump_key"}
    keys = {va: name for va, symbols in member.symbols().items() for name in symbols if name in names}
    require(len(keys) == 2 and set(keys.values()) == names, "test keys absent or ambiguous")
    matched = dict.fromkeys(keys, 0)
    table, = [s for s in member.sections if s["name"] == "__static_if"]
    text = next(s for s in member.segments if s["name"] == "__TEXT_EXEC")
    expected = bytearray(before)
    patched = set()
    for slot in range(table["va"], table["va"] + table["size"], 16):
        key = chain.get(slot + 8, (0, 0))
        owner = key[0] & ~3
        if owner not in keys:
            continue
        delta, target, flags = struct.unpack("<iiQ", root.read(slot, 16))
        va = slot + delta
        if not text["va"] <= va <= text["va"] + text["filesize"] - 4:
            continue
        require(not key[1] and va not in patched and va not in authenticated_entries and va % 4 == 0
                and target % 4 == 0 and -(1 << 27) <= target < 1 << 27 and (flags & 3) == (key[0] & 3),
                "invalid static_if site or pointer")
        at = root.offset(va, 4)
        branch = 0x14000000 | ((target >> 2) & 0x3FFFFFF)
        want = 0xD503201F if flags & 1 else branch
        require(struct.unpack_from("<I", before, at)[0] in (0xD503201F, branch), "invalid preimage")
        struct.pack_into("<I", expected, at, want)
        matched[owner] += 1
        patched.add(va)
    require(all(matched.values()), "one or more test keys had no sites")
    code = next(s for s in member.sections if s["name"] == "__text" and s["segment"] in ("__TEXT", "__TEXT_EXEC"))
    mac, = [s for s in member.sections if s["name"] == "__fips_hmacs"]
    require(mac["size"] == 32, "invalid POST HMAC extent")
    begin = root.offset(code["va"], code["size"])
    signature = root.offset(mac["va"], mac["size"])
    require(not begin <= signature < begin + code["size"], "POST HMAC overlaps hashed code")
    expected[signature:signature + 32] = hmac.digest(b"\0", expected[begin:begin + code["size"]], "sha256")
    require(expected == after, "sealed bytes differ from exact static_if and POST transform")
    return dict(before_sha256=hashlib.sha256(before).hexdigest(), after_sha256=hashlib.sha256(after).hexdigest(),
                bytes=len(before), tested_static_if_sites=len(patched), source_crypto_post_hmac="MATCH",
                other_binary_changes=False, runtime="NOT_OBSERVED")


def main():
    before, after, kit, out = map(Path, sys.argv[1:5])
    require(hashlib.sha256(kit.read_bytes()).hexdigest() ==
            "2a2561308b27ace4e21dd4e45924bdeca937ee13047b7c6fd5ce580018f68747", "decoder identity")
    result = verify(runpy.run_path(str(kit))["Image"], before.read_bytes(), after.read_bytes())
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
