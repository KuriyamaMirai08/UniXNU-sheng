#!/usr/bin/env python3
"""Decode Qualcomm A/B GPT attributes for the 16 archived slot partitions."""
import json
from pathlib import Path

ROOT = Path(r"C:\Users\13463\Documents\ChatGPT\双系统")
INV_PATH = ROOT / "stage0c2-local-repairs/outputs/verification-20261121/2f-slot-inventory.json"
HIST_PATH = ROOT / "research-20261118/historical-gpt-recheck.json"
STOCK_PATH = ROOT / "research-20261118/stock-rom-gpt-reference.json"
OUT_PATH = Path(__file__).resolve().parent / "gpt-attributes-decoded.json"


def decode_qcom_attr(val: int) -> dict:
    return {
        "raw_hex": f"0x{val:016x}",
        "low_bits_hex": f"0x{val & 0xffffffffffff:012x}",
        "priority": (val >> 48) & 0x3,
        "active": bool((val >> 50) & 0x1),
        "retry_count": (val >> 51) & 0x7,
        "successful": bool((val >> 54) & 0x1),
        "unbootable": bool((val >> 55) & 0x1),
        "upper_byte_56_63_hex": f"0x{(val >> 56) & 0xff:02x}",
    }


def index_partitions(doc: dict) -> dict:
    out = {}
    for lun, obj in doc.items():
        if isinstance(obj, dict) and "partitions" in obj and lun in ("sda", "sdb", "sdc", "sdd", "sde", "sdf"):
            for p in obj["partitions"]:
                out[p["name"]] = (lun, int(p["attributes"], 16))
    return out


def main():
    inv = json.loads(INV_PATH.read_text(encoding="utf-8"))
    hist = index_partitions(json.loads(HIST_PATH.read_text(encoding="utf-8")))
    stock = index_partitions(json.loads(STOCK_PATH.read_text(encoding="utf-8")))

    slot_names = [k for k in inv["partitions"] if k.endswith("_a") or k.endswith("_b")]
    decoded = {}
    for name in slot_names:
        lun_h, attr_h = hist[name]
        lun_s, attr_s = stock[name]
        assert lun_h == lun_s
        decoded[name] = {
            "lun": lun_h,
            "historical": decode_qcom_attr(attr_h),
            "stock": decode_qcom_attr(attr_s),
            "differs": attr_h != attr_s,
        }

    ba = decoded["boot_a"]["historical"]
    bb = decoded["boot_b"]["historical"]
    other_upper_bytes = {
        k: v["historical"]["upper_byte_56_63_hex"]
        for k, v in decoded.items()
        if k not in ("boot_a", "boot_b")
    }

    result = {
        "scope": "archived historical vs stock GPT attribute bitfield decode; current device unobserved",
        "bitfield_spec": {
            "priority": "bits 48..49",
            "active": "bit 50",
            "retry_count": "bits 51..53",
            "successful": "bit 54",
            "unbootable": "bit 55",
        },
        "summary": {
            "authority": "Qualcomm ABL treats boot_a/boot_b GPT attributes as slot-selection authority.",
            "historical_boot_a": {
                "raw_hex": ba["raw_hex"],
                "priority": ba["priority"],
                "active": ba["active"],
                "retry_count": ba["retry_count"],
                "successful": ba["successful"],
                "unbootable": ba["unbootable"],
            },
            "historical_boot_b": {
                "raw_hex": bb["raw_hex"],
                "priority": bb["priority"],
                "active": bb["active"],
                "retry_count": bb["retry_count"],
                "successful": bb["successful"],
                "unbootable": bb["unbootable"],
            },
            "other_partitions_upper_byte_56_63_hex": other_upper_bytes,
            "conclusion": (
                f"Historical boot_a (active={ba['active']}, successful={ba['successful']}, "
                f"unbootable={ba['unbootable']}, priority={ba['priority']}, retry={ba['retry_count']}) "
                f"was the active successful slot; boot_b (active={bb['active']}, successful={bb['successful']}, "
                f"unbootable={bb['unbootable']}, priority={bb['priority']}, retry={bb['retry_count']}) was inactive."
            ),
        },
        "partitions": decoded,
        "device": "NO-GO",
    }
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(decoded)} partitions)")


if __name__ == "__main__":
    main()
