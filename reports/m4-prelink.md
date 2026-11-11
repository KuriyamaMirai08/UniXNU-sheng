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

## Reviewed callable identities

The second real run, [43069929349](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43069929349),
reused the map and reproduced all 21 unresolved pointers in about ten
seconds of emission. No native/reference rebuild occurred.

`scripts/m4-prelink-symbols.json` records two recovered identities with
original function extents, byte hashes, named native targets and source
reasoning: `vm_map_page_size` and `ml_stack_remaining`. The runtime stage
copies this evidence into a separately named fixture using the prelink
engine's existing reviewed-symbol interface. Its signature invalidates
old maps; the engine checks original bytes and resolves native symbols.
No matching heuristic or ABI check is weakened. These are callable KPIs;
their different internal field offsets are not patched or treated as
proof that private structure layouts match.

The selected OS profile explicitly uses public xnu-12377.121.6 with
Darwin 26 compatibility patches against the stripped 24A446 collection.
A successful native link therefore does not establish that every private
24A446 interface exists or has the same ABI. Remaining private bindings
require individual implementation/signature evidence before publication.

## Strict retry after the two identity fixes

[Run 43071105217](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43071105217)
on `be828a08381d3857058ca028e024903f7a88c22f` confirmed both named targets
were bound by the reviewed mechanism. Unresolved pointer references fell
from 21 to 19. Native/reference input digests were unchanged. All 57
selected closure entries remained; the formal emitter processed 111,618
native chain sites, 130,884 retained kext chain sites, 81,116 rebound kext
pointers and 561 original adapter branches. Split relocations processed:
kind 3: 17,297; kind 4: 53; kind 5: 164,606; kind 6: 175,610;
kind 7: 4,050; pointer relocations: 111,618. No fallback stubs were used.

The actual DATA interval is `[0xfffffff00b834000, 0xfffffff00ba1c000)`.
Reconstructing the same production Layout from these retained inputs
finds the first retained Libm DATA byte at exactly `0xfffffff00ba1c000`:
`0x1e8000` fits this closure with **zero growth headroom**. Increasing it
by 16 KiB would collide with Libm; any native input change must rerun the
actual layout check. The M4 stage also records these boundary fields.

Remaining strict failures (output address space uses slide 0x1f000000000):

| Owner | Unresolved pointer references |
| --- | ---: |
| AppleARMPlatform | 7 |
| AppleARMWatchdogTimer | 3 |
| ApplePMGR | 2 |
| IOHIDFamily | 1 |
| IOSurface | 1 |
| AppleImage4 | 1 |
| Image4 | 4 |

The two non-code targets in original address space are
`0xfffffe00070446a8` (kernel TEXT const) and `0xfffffe000b8b3ce8`
(kernel DATA common). The remaining code includes the original
`processor_info` identity at `0xfffffe000ad53f60`: its disassembly handles
flavor 3 with count >= 12, whereas the selected public source's
`osfmk/kern/processor.c` implements basic/load flavors and delegates others
to cpu_info. A named binding alone cannot qualify this additional flavor.
The Image4 targets `0xfffffe000b2a1694` and `0xfffffe000b2a170c` construct
monitor requests with operation constants 0x34 and 0x35. Their exact ABI
and required implementation are not yet proven. They remain unresolved,
not mapped to a superficially similar function or panic stub.

The strict writer reported `candidate_written=false`,
`mapping_complete=false`, `stubbed={}`. There is no qualified final
prelink artifact/hash. The retained failure JSON SHA-256 is
`a242b95a2883df2912d8c557429381c3478dbf331868864fc4b374d1f71c00b3`.
The native input SHA-256 remains
`31f8273297025436fa9814b9540329b439af45afd661f7f6836476401a9ec15b`.

Next work is identity/ABI recovery for these 19 references, with a real
implementation or adapter wherever the public source lacks the required
interface. Until those are proven, final fileset structure checks,
complete binding qualification, early init, runtime selftests and device
boot remain unverified. Failures, maps and inputs remain on the Mac;
this stage never cleans build objects, headers or archives.
