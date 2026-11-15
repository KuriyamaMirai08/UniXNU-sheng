"""Declare only capabilities backed by the selected source and archive plan."""
import hashlib
import json
import os
from pathlib import Path
import re


def compiler_flags(tree):
    if os.environ.get("UNIXNU_SHENG_AUTHOR_AUDIT") != "1":
        return []
    if (os.environ.get("UNIXNU_IPSW_BUILD"), os.environ.get("UNIXNU_XNU_TARGET"),
            os.environ.get("UNIXNU_XNU_ARCH")) != ("24A446", "ios", "arm64e"):
        raise ValueError("Explicit optional-provider plan is qualified only for 24A446 arm64e iOS")
    tree = Path(tree)
    prepared = tree / ".cache/xnu-work"
    inputs = {}
    for name, symbol in (("osfmk/arm64/machine_routines.c", "ml_static_mfree_prepare"),
                         ("iokit/Kernel/IOMemoryDescriptor.cpp", "iokit_physical_descriptor_close_notify")):
        data = (prepared / name).read_bytes()
        # These two providers are defined by the macOS-only patches. Refuse a
        # changed selection; never hide a provider that is present in the source.
        if re.search(rb"\b" + symbol.encode() + rb"\s*\(", data):
            raise ValueError("A real optional provider is present; review its enabled path: " + symbol)
        inputs[name] = dict(sha256=hashlib.sha256(data).hexdigest(), provider=symbol, present=False)
    builder = (tree / "scripts/build-gop-legacy-display-27.py").read_text()
    if "if MACOS:\n    ETH_OUT" not in builder or "if MACOS:\n    AES_OUT" not in builder:
        raise ValueError("Ethernet/software-AES archive selection changed")
    # The selected iPadOS builder does not compile either macOS provider. Their
    # full implementations and invocation branches remain for enabled builds.
    header = ("// Generated from the audited 24A446 provider selection.\n"
              "#define SHENG_HAS_ETHERNET 0\n#define SHENG_HAS_SOFTWARE_AES 0\n"
              "#define SHENG_HAS_PAYLOAD_RELEASE 0\n#define SHENG_HAS_PAGER_CLOSE 0\n").encode()
    directory = tree / "build/sheng-optional-providers"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ShengOptionalProviders.h"
    if path.exists() and path.read_bytes() != header:
        raise ValueError("Capability header has unreviewed changes")
    path.write_bytes(header)
    receipt = dict(profile="ipados-27.0.1-24A446", source_inputs=inputs,
                   macos_provider_objects_selected=False, header_sha256=hashlib.sha256(header).hexdigest(),
                   absent_functions=["_sheng_ethernet_probe", "_sheng_software_aes_probe", "_ml_static_mfree_prepare",
                                     "_iokit_physical_descriptor_close_notify"],
                   provider_functions_synthesized=False, default_upstream_weak_import_path_retained=True)
    (directory / "provider-plan.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return ["-include", str(path)]
