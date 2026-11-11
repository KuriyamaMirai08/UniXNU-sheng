# Strict M4 prelink

Dispatch package on the PR branch with `runner_location=self-hosted`,
`self_hosted_stage=prelink`, `os=27`, empty Seed inputs and init_data false.
The same persistent `public-xnu-v1` tree is used. This stage never invokes
the archive dispatcher, XNU make, native link or installation preparation.

The native input must match the verified native-link SHA-256
`31f8273297025436fa9814b9540329b439af45afd661f7f6836476401a9ec15b`.
The RELEASE reference must match its existing build receipt. Only the
original KernelCache IPSW member is retrieved with the existing range
reader if the pinned decompressed cache is absent. The kernelcache digest
must remain `38e6d9fa5f789b8228f4617ef4c6d2a3fd8ab564abdc9b62920f1db53fc1780a`.

The stage calls the original `kernel.prelink` engine and regression policy,
with every current root retained. It removes the historical profile's
`--allow-missing` option in this invocation, disabling unmatched-function
panic stubs and incomplete candidate publication. No native input is
rewritten and no diagnostic DATA-hole patch is applied.

Prelink attempt directories are retained under the persistent kernel
output directory, including after failure. Existing atomic publication,
input-bound map caching and regression checks are kept. Per-attempt logs,
input digests, actual-input DATA layout evidence, mapping reports and
post-emission structure reports are uploaded as public compilation logs.

Success requires complete non-stubbed bindings, no unproven kernel page
references, real MH_FILESET structure, arm64e native member, bounded
segments/sections, valid root fixup chains and the unchanged regression
policy. The emitter checks placement collisions, split-segment relocation
kinds/ranges, authenticated pointer formats and original adapter branches.
The actual DATA placement is recorded separately from emission success;
a capacity estimate does not count as a completed prelink.

Static emission and ABI checks do not establish runtime correctness. No
device key, installation Seed or device-bound installation image is used.

## First real emission

Run 43069001174 used the actual M4 native/reference binaries and pinned
original collection. Its 57-entry closure placed native DATA at
`0xfffffff00b834000` with size `0x1e8000`, without overlap. The real emitter
processed 111,618 native chained pointers and rebound 561 adapter branches.
Strict output was refused for 21 unresolved pointer references; no panic
stubs were enabled. The failed report and input-bound pairing map remain
in the persistent output and per-attempt artifact.

On a first failure for each input triple, the workflow exports hardlinks
to the three public kernel inputs with their recorded digests for offline
binding diagnosis. No disk-copy of the images or installation input is
introduced, and a content marker avoids uploading them on every retry.
