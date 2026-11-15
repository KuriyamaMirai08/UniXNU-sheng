# Clean kernel startup readiness

The clean build proves construction from fresh inputs. Its `loadable=false`
and `runtime_qualified=false` fields do not describe a failed loader test:
the pinned `XnuPrelink/fileset_emit.py:741` sets both to constants. The current
kernel remains unsuitable for recommending a new device experiment because
its imported bindings are incomplete and it has no corresponding boot image.
The first-frame failure's runtime cause has not been established.

The retained baseline is
[run 43615501493](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43615501493),
build commit `0f16f7de8ddf583458967d1a7239c8b101542bfe`, standard hosted
macos-26 ARM64. It is distinct from the previous M4 incremental evidence.
This investigation invoked no full build, device operation or installer.

## Acceptance fields and the actual loading boundary

| Field | Owning condition | Meaning |
| --- | --- | --- |
| `mapping_complete` | `not bool(emit.missing)` | No unresolved reference recorded during emission. Panic replacements are counted in `stubbed`, so this field alone cannot qualify bindings. |
| `loadable` | Constant `False` | Conservative unqualified status. There is no dynamic loading result in this field. |
| `runtime_qualified` | Constant `False` | No runtime qualification is issued by the emitter. |

With the profile's historical `--allow-missing`, unknown function starts use
`_unixnu_fileset_unmapped`, which panics when called. Unknown data references
have no such fallback and retain the old translated address. Strict emission
uses neither fallback nor `--allow-missing` and refuses a candidate with gaps.
The original regression policy bounds additional gaps and requires particular
adapter branches; its permitted baseline is not a boot qualification.

The unmodified production DarwinBoot C parser was compiled on the host and
accepted the actual clean fileset, the retained native input and the historical
installed kernel with `EFI_STATUS=0`. Its positive and negative fixtures
passed. Fileset/member bounds, fixups, relocation space and relocated HMAC
also passed the earlier clean-build audit. Thus no observed format rejection
explains `loadable=false`. These tests do not exercise EFI allocation, actual
DTB selection, GOP, ExitBootServices or the kernel entry on sheng.

## Two incorrect data imports

| Symbol / importer | Incorrect baseline target | Real native target after placement | Evidence and effect |
| --- | --- | --- | --- |
| `PE_arm_debug_panic_hook` / AppleARMWatchdogTimer | `0xfffffff0070446a8` | `0xfffffff00b859188` | Typed mutable pointer object; retain `PE_arm_panic_hook` at `0xfffffff00b521b18` and authentication fields `[1,0,10942,0]`. Wrong Watchdog loads/CAS could corrupt panic handling if reached. |
| `kext_assertions_enable` / IOHIDFamily | `0xfffffff00b8b3ce8` | `0xfffffff00b8343d8` | The stale address is `zone_array+0x20868`, not the flag. The real DEVELOPMENT integer remains 1; 81 original HID use sites read it. Reading zero at the stale address can hide an assertion rather than prove validity. |

The old installed kernel contains these same stale imports and reached
userspace. They are real binding defects; their presence alone cannot explain
the later userspace wait. Preserving the real assertion flag may expose a
previously hidden driver/ABI assertion. Disabling it is not a repair.

## Nineteen panic import occurrences

These are 18 function targets: `cpu_number` has two importers. Together with
the two data objects, the inventory has 21 occurrences and 20 unique targets.
The full original slot, authentication, function hashes, veneer callers and
per-item effects are retained locally in `REFERENCE_INVENTORY.json` and its
Chinese report. Addresses below are original cache addresses.

| Original target | Importer / occurrences | Interface | Status and runtime scope |
| --- | --- | --- | --- |
| `0xfffffe000ae14d08` | IOGPUFamily / 1 | `vm_map_page_size` | Real native mapping validated. Three static GPU memory callers; a panic here can interrupt graphics if reached. |
| `0xfffffe000aec5fe0` | IOCryptoAcceleratorFamily / 1 | `ml_stack_remaining` | Real native mapping validated. Native stack rules retained; relevant crypto caller can panic in the baseline. |
| `0xfffffe000b4b6724` | IOSurface / 1 | `IOMemoryDescriptor::ktraceEmitPhysicalSegments` | Real trace/segment implementation validated; gates and return codes remain. Baseline's external panic replacement bypasses its internal trace gates. |
| `0xfffffe000aebcc3c` | AppleARMPlatform / 1 | `ml_arm_sleep` | Real native sleep state machine validated; Qualcomm physical sleep compatibility is separate. |
| `0xfffffe000aebdee4` | ARMPlatform and Watchdog / 2 | `cpu_number` | Real native thread/CPU index validated, without transplanting old thread offsets. |
| `0xfffffe000aebdef4` | AppleARMPlatform / 1 | `ml_get_wake_timebase` | Actual native producer/consumer object validated; wake path is conditional. |
| `0xfffffe000ad6df18` | ApplePMGR / 1 | `sched_enable_acc_rail` | Real scheduler/topology locking and update validated; not Qualcomm rail support. |
| `0xfffffe000ad6e204` | ApplePMGR / 1 | `sched_disable_acc_rail` | Real complementary scheduler operation validated; Apple hardware matching is conditional. |
| `0xfffffe000b4ca1d0` | AppleARMPlatform / 1 | `IOCPUInterruptController::IOCPUInterruptController` C1 | Real constructor/vptr/refcount/metaclass implementation validated. |
| `0xfffffe000b4ca260` | AppleARMPlatform / 1 | `IOCPURunPlatformQuiesceActions` | Real callback queue/ABI/authentication/error reduction validated. |
| `0xfffffe000b4ca2e8` | AppleARMPlatform / 1 | `IOCPURunPlatformActiveActions` | Real callbacks and native hibernate/assertion behavior validated. |
| `0xfffffe000ad53f60` | Watchdog / 1 | `processor_info` | Only current flavor 1/count 5 consumer is qualified; closure/import/veneer/caller guard remains. No flavor 3 implementation is claimed. |
| `0xfffffe000b5a3ba8` | AppleImage4 / 1 | `kernel_image4_storage_data` | Real zeroed 0x1400-byte storage validated against >=0x390/8-alignment requirement. Observed caller executes only for monitor type 1; native type is 0. |
| `0xfffffe000b433e68` | AppleARMPlatform / 1 | `IOService::CallPlatformFunction` DriverKit RPC | Still unresolved. Two conditional ARMPlatform callers. |
| `0xfffffe000b2a1694` | Image4 / 1 | TXM command 0x34, three arguments | Still unresolved; nonce-digest initialization path. |
| `0xfffffe000b2a170c` | Image4 / 1 | TXM command 0x35, one argument | Still unresolved; Image4 user-client dispatch. |
| `0xfffffe000b2a1778` | Image4 / 1 | TXM command 0x36, two buffer/length pairs | Still unresolved; entitlement and monitor-type gates. |
| `0xfffffe000b2a1798` | Image4 / 1 | TXM command 0x37, one buffer/length pair | Still unresolved; entitlement and monitor-type gates. |

ArmDTPlatform and ArmCpu implement this board's platform/CPU services, with
probe scores 5000 and 2000 respectively. AppleARMCPU has score 100 and Apple's
Watchdog/PMGR require Apple hardware providers/names. This lowers the priority
of their conditional paths, without proving they never execute. ARMPlatform
also has IOResources personalities, so module absence cannot be inferred.
None of the 561 native original-branch adapters targets these platform,
Watchdog, PMGR or Image4 modules; their retained metadata/code remains.

## Five remaining interfaces

DriverKit's exported signature is
`IOService::CallPlatformFunction(OSString*,bool,OSDictionary*,OSDictionary**,OSDispatchMethod)`.
The observed RPC ID is `0xbf66f4287c60ef85`. The original backend at
`0xfffffe000b50a088` applies TLS/owner checks, retrieves a typed handler through
the old `callPlatformFunction` virtual slot `+0x3a8`, converts OSString to
OSSymbol, invokes the callback with discriminator `0xac0`, preserves ownership
and returns errors for missing/disallowed handlers. Instructions
`0xfffffe000b46dbc0..0xfffffe000b46dbd0` prove initialization of that query
symbol from `IOUserPlatformFunctionHandlerGet`. The old `OSSymbol + four void*`
API is not this RPC and cannot receive a direct binding.

The macOS profile's newer compatibility patch supplies a `LOCAL SERIALIZABLE`
IDL declaration but its implementation only returns unsupported. That patch
was not applied. A real repair still requires the generated dispatcher ABI,
serialization/reply checks, complete TLS/provider/lifetime behavior and a
functional registered callback backend. The SDK/doc mirror establishes the
signature, not the implementation on the current native kernel.

The same patch suggests four names: `image4_v2_set_nonce_digest`,
`image4_v2_roll_nonce`, `image4_v2_load_diavlo_root_ca` and
`image4_v2_load_local_policy`. They remain naming leads, not proven bindings
for this binary. Its fixed 0xffff/empty implementations were rejected.
Original bytes establish TXM transport, allocation/copy, ownership transfer,
return tags and failure reclamation; no equivalent non-monitor backend or
complete nonce/authenticated-state contract is available here.

The original emitter already removes the dependency Image4 personality,
retaining its security kmod and code. Packed kmod pointers identify
`0xfffffe000a9e23f0` as its start callback and the native registration point
stores the real V2 interface table. Forty-one directly traversed functions
from the original start path do not reach the four unresolved veneers.
Constructors register classes, while nonce/object operations are indirect
service/user-client paths. This is bounded static evidence, not a complete
dynamic call graph. The native code-signing configuration sets monitor type
0; the two policy-load callers skip their monitor calls for type 0. Neither
fact permits inventing a successful TXM implementation or dropping security
checks.

## Historical process evidence

The raw tag-3360 snapshot recorded zero `swap_submit`/`validateSwap` calls,
five base containermanagerd starts/exits, one system-container start with
zero exits, and 199 xpcproxy exits, all status 0. The exec hook's zero start
count does not establish that the proxy never launched. IPC-full waiting in
one sampled thread does not establish deadlock.

The same-boot tag-3361 snapshot shows SpringBoard synchronously waiting for
`LSCopyServerStore`, and lsd waiting in a container query for an XPC reply.
The system container was alive; the base service was absent only in the last
process pass. Failed receiver-task lookups do not establish a missing peer.
One last-published stack cannot prove the same wait persisted over 29 passes.
The later tag-3363 files record image validation/boot dispatch, without an
observed exit-reason result.

The historical installed kernel reached userspace with the same two data
errors and relevant panic imports. There is no captured unmapped-function
panic, executed callsite, syscall failure or service-exit reason linking the
21 imports to the LaunchServices/container wait. Generic GPU/Crypto/IOSurface
bindings deserve repair for correctness; changing IPC or container semantics
without the missing runtime cause would be speculative.

## Kernel and boot-image relationship

| Artifact | Bytes / SHA-256 | Relationship |
| --- | --- | --- |
| Current clean `kernel.macho` | 96,649,216 / `4c8a0e7e9c786aa95bc7bafd8b938ea0db2866b33d3d888be5e0362b460a70a4` | Original experimental 2 missing / 19 panic import occurrences remain. |
| Retained native input | 28,212,032 / `2d1071d451f27bcd330a688a2579bd789b9c5795b1d5e670239850629ec665d9` | Source-built native used by the reviewed recovery. |
| Historical installed kernel | 96,649,216 / `fee25c2470d56e3d6fcd0352cef5f8b4fcab361cc2cd869775320b2ea94b7cbc` | In historical normal/control payloads that reached userspace. |

Four retained boot images were parsed without modification. Android v0,
page size 4096 and SHA-1 header ID passed. The Android kernel field contains
gzip BootShim/UEFI plus eight firmware DTBs; XNU is inside the FAT32 ramdisk
at `/EFI/UniXNU/Payloads/kernel.macho`. Both FAT copies, directory/cluster
chains and eight payload files passed. ARM64 shim load is `0xa7100000`.
The UEFI firmware SHA-256 is
`4e0c22e8bc13b6399bd059908152ccf2f3c163caf2a57a5f02d67cc7b1ba1270`;
the contiguous DTBs' SHA-256 is
`7d3b438ffa2535aaed96b5e80a431f03e3286eb91b58a297484efc9166141e22`.
None contains the current clean kernel. No current clean boot.img exists.

The production ADT/trustcache/packed-disk parsers and GPU-addon header passed
host checks and four negative cases. The 5,100,273,664-byte owned window has
sufficient computed placement for the historical payload layout. KeepPacked
retains the sparse Data image rather than allocating its 215-GiB logical size.
The production VerifiedRoot parser verified two real policy headers using
real SHA-256/RSA3072 PKCS#1 v1.5 and rejected 16 negative cases. The public
anchor/policy match the retained clean inputs; current device root data was
not read again. These checks do not establish firmware execution or current
partition contents.

## Reproducible recovery and verification

[clean_prelink_recovery.py](../scripts/clean_prelink_recovery.py) adds a
clean-input-specific entry without changing the historical M4 hash contract.
[The contract](../scripts/clean-prelink-contract.json) pins exact inputs,
matcher/emitter modules, fixture inventory, reviewed evidence, roots, closure
consumer contracts and the original regression source/policy.
[The fixture](../scripts/clean-prelink-symbols.json) independently revalidates
13 functions and two data objects against the clean native executable.
Its original byte encoding is retained by a file-specific Git attribute;
checkout newline conversion cannot invalidate the reviewed hash or pairing.
All changed function words from the reviewed historical native were proven
split relocations or same-named B/BL destinations with unchanged addends.

The actual production emission reduces 21 failed import occurrences to five,
with `stubbed={}`. Independent final-byte parsing verifies all 16 recovered
slots, native symbols, preserved authentication, assertion value 1 and real
panic handler. It retains the same 57-entry closure, 561 adapter branches and
0x1e8000 DATA size. Inputs are checked again before publication.
The final guarded attempt returns 1, `candidate_written=false`,
`source_inputs_modified=false`. An incomplete in-memory hash is evidence only;
it is not a delivered kernel.

[Targeted tests](../scripts/test-clean-prelink-recovery.py) passed 12 cases:
real original contracts, changed input/function bytes, changed assertion flag,
panic authentication, processor consumer, closure and extra fixture;
incomplete/stub publication refusal; original regression and required-branch
checks. Original reports are saved on refusal. No acceptance field, policy,
security module or production function was weakened. There is no new native
source change needing another full compilation.

The verified implementation commit is `bdbf6dbda75d7055bc99df79de3674617be50cff`. Its Git archive
preserves the exact fixture hash and was used for the final 12-case test run
and strict emission refusal. The report/porting evidence update follows this
commit; it does not replace the identified tested code.

Use the original retained files and a fresh attempt directory:

```sh
python -B scripts/clean_prelink_recovery.py \
  --kit /path/to/retained/XnuPrelink \
  --kernelcache /path/to/kernelcache.decompressed \
  --native /path/to/native-prelink-input.macho \
  --reference /path/to/release-reference.macho \
  --map /path/to/recovery-01/strict.map.json \
  --policy /path/to/original/prelink-regression.json \
  --regression-source /path/to/original/unixnu/kernel.py \
  --attempt /path/to/new-attempt
```

The expected current result is strict refusal for the same five interfaces.
Future native/ABI/closure changes require a new independent review and input
contract. This command cannot run a build or interact with a device.

## Readiness decision

The current artifacts do not support recommending a new controlled device
boot experiment. The immediate missing deliverables are a strictly complete
real-binding kernel, a corresponding assembled boot image with identified
firmware/payload/trust/root inputs and renewed static checks for that exact
image. The five interfaces need actual proven implementations/bindings;
bounded static non-reachability does not satisfy current strict emission.
The prior first-frame problem additionally needs the actual container request,
service-exit/error evidence or captured executed kernel callsite before a
causal fix can be claimed. Final display/power/EFI behavior remains unverified.
No automatic flashing, partition write or device start is part of this work.
