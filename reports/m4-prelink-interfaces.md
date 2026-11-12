# M4 retained-interface recovery

## Inputs and scope

Starting failure: [43071696215](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43071696215),
branch commit `10f4766c9e7b99181845cb735c92d15dd2c95476`.
Its 19 pointer references deduplicate to 18 original targets: 16 functions
and two data objects. CPU number has two unresolved import slots.

[Machine-readable inventory](m4-prelink-interfaces.json) records every failed
owner/import slot, original/output target, target section, complete function
extent and SHA-256, instruction words, root chained-pointer xrefs,
authenticated import veneer, and statically recovered B/BL caller positions.
`direct_address_xrefs` are conservative straight-line ADR(P) evidence;
dynamic/aliased data accesses are not claimed exhaustive. All failed
owner/slot multiplicities are checked against the original fixup chains.
Addresses below are **original**, before collection slide `0x1f000000000`.

Reproduce the inventory with the pinned `XNU_PRELINK_KIT` environment and:

```sh
python3 scripts/audit-m4-prelink-interfaces.py --original kernelcache.decompressed   --report kernel.failed.json --output interfaces.json
```

The native checkpoint stays
`31f8273297025436fa9814b9540329b439af45afd661f7f6836476401a9ec15b`;
reference checkpoint stays
`4f5ab3149a1f773d2ff1f030f3606ea46f85045040e4362112b3c1a49b12b8b9`.
No XNU/archive/CoreCrypto source, object, header, native link, root list or
native DATA size is changed. The 57-member dependency closure is pinned
again for the scoped processor_info contract. No device/installation input.

## Recovered functions and objects

Exact function hashes, extents, named native implementation hashes and
per-function arguments/returns/side effects are in
[`m4-prelink-symbols.json`](../scripts/m4-prelink-symbols.json).
All rows use the existing reviewed matcher; no heuristic is relaxed.

| Original target | Owner / refs | Verified identity and repair |
| --- | --- | --- |
| `0xfffffe000aebcc3c` | ARMPlatform / 1 | `ml_arm_sleep(void)` noreturn; boot/secondary CPU paths, sleep token 0x50535553, wake_abstime producer, cache maintenance and CoreSight unlock sequence match public cpu.c and native implementation. |
| `0xfffffe000aebdee4` | ARMPlatform + Watchdog / 2 | `cpu_number(void)` returns 16-bit current_thread machine CPU index in w0. Source and caller uses prove identity despite internal thread offsets changing. |
| `0xfffffe000aebdef4` | ARMPlatform / 1 | `ml_get_wake_timebase(void)` returns the exact uint64_t global produced by proven ml_arm_sleep; producer/consumer addresses verified on both sides. |
| `0xfffffe000ad6df18` | PMGR / 1 | `sched_enable_acc_rail(unsigned die,unsigned cluster)`; topology CPU mask, synchronous cluster lock, OR required-online mask, reason 5, powered-core update and pulled-thread flush. |
| `0xfffffe000ad6e204` | PMGR / 1 | `sched_disable_acc_rail(unsigned die,unsigned cluster)`; clears that mask and asynchronously signals powered-core update. Distinct lock/update semantics retained. |
| `0xfffffe000b4ca1d0` | ARMPlatform / 1 | `IOCPUInterruptController::IOCPUInterruptController()`; independent class vtable/metaclass pairs, refCount +8, instanceCount +0x24, same 0xcda1 vptr signature and native base-constructor chain. |
| `0xfffffe000b4ca260` | ARMPlatform / 1 | `IOCPURunPlatformQuiesceActions()`; queue index 2, eight-register callback ABI, action-record fields, 0x2753 callback signature and first-error reduction. Native assertions retained. |
| `0xfffffe000b4ca2e8` | ARMPlatform / 1 | `IOCPURunPlatformActiveActions()`; adjacent queue index 3, same callback ABI; native pre/post hibernation calls and assertions retained. |
| `0xfffffe000ad53f60` | Watchdog / 1 | `processor_info` for the **proven flavor 1 only**; checked closure/import/veneer/caller contract described below. No flavor 3 implementation claimed. |
| `0xfffffe000b4b6724` | IOSurface / 1 | `IOMemoryDescriptor::ktraceEmitPhysicalSegments()`; debug ID 0x05410004, preparation/descriptor gates, physical-segment iteration, same IOReturn success/bad-argument contract. Native trace packing/checks retained. |
| `0xfffffe000b5a3ba8` | AppleImage4 / 1 | `kernel_image4_storage_data(size_t*)`; original TXM-specific storage diagnostic identifies wrapper; native real 0x1400-byte, 8-aligned, zero-initialized storage satisfies selected caller's >=0x390 size/alignment/init contract. No panic substitution. |
| `0xfffffe00070446a8` | Watchdog / 1 | **Data**, `PE_arm_debug_panic_hook`: pointer size/alignment 8, original const slot NULL, 8-byte load/CAS and callback discriminator 0x2abe; native PE_panic_hook loads/authenticates same symbol. Keep native existing PE_arm_panic_hook and authenticated chain, not NULL. |
| `0xfffffe000b8b3ce8` | IOHIDFamily / 1 | **Data**, `kext_assertions_enable`: int size 4, required alignment 4, original __common is S_ZEROFILL and virtual zero; 81 IOHID read sites gate MACH_ASSERT failures (BRK 0xbffc). Native __data is 1, preserving DEVELOPMENT assertions. Following padding is not part of the object. |

The data slots are verified separately from function starts: actual section
type, mapped bounds, object size, alignment, contents and, for the hook,
the existing authenticated target are checked. No data slot is treated as
code or filled with invented bytes.

Public implementation evidence is pinned to Apple XNU
[`ac9718fb1af618d5ce8678d0dc6e8a58f252216f`](https://github.com/apple-oss-distributions/xnu/tree/ac9718fb1af618d5ce8678d0dc6e8a58f252216f):
[cpu.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/arm64/cpu.c),
[cpu_common.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/arm/cpu_common.c),
[sched_prim.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kern/sched_prim.c),
[processor.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kern/processor.c),
[IOPlatformActions.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Kernel/IOPlatformActions.cpp),
[IOMemoryDescriptor.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Kernel/IOMemoryDescriptor.cpp),
[assert.h](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kern/assert.h),
[debug.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kern/debug.c),
[pexpert.h](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/pexpert/pexpert/pexpert.h),
[non-monitor Image4](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/kern/code_signing/xnu.c),
[TXM Image4](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/kern/code_signing/txm.c).

## processor_info flavor 3 is not silently accepted

The original function's flavor 3 requires count >=12, performs a task/proc
permission/entitlement gate, snapshots processor counters, writes 48 bytes
including six 64-bit quantities, and returns count 12. Counter units,
field names, authorization policy and synchronization cannot be inferred
safely from its numeric flavor. Public processor_info handles basic/load
and delegates other flavors to cpu_info. No flavor 3 adapter is invented.

The selected Watchdog has exactly one authenticated veneer call at
`0xfffffe00087170e0`, fixes w1=1 at `0xfffffe00087170dc` and initializes
count=5 at `0xfffffe00087170ac`. It consumes the basic running field at
info+8. The full caller's 252-byte digest is
`f4bc0ca2d069cee00ae22cda6790e29f0e216be9667f9c4b04cca8c3c6699535`.
The pre-emission evidence guard checks this body, parameter instructions,
all selected import slots, authenticated veneer and static callers, plus
exact closure identity. New consumers/closure changes fail before pairing.
This qualifies the current imported BASIC_INFO contract, not the entire
original processor_info flavor set. Native kernel-internal callers keep
their source-built implementation.

## Five unproven interfaces

| Original target | Owner / call(s) | Evidence and actual remaining blocker |
| --- | --- | --- |
| `0xfffffe000b433e68` | ARMPlatform, two BL callers in inventory | Six incoming registers x0..x5; x2 boolean, x4 output dictionary pointer, x5 optional supermethod callback. Marshals an IORPC, expects reply ID 0xbf66f4287c60ef85 and OSDictionary metaclass. No matching reply-ID immediate exists in the native kernel; available CopyProperties/other similarly named methods have different register/IDL contracts. Exact method identity and corresponding implementation remain unproven. |
| `0xfffffe000b2a1694` | Image4, BL `0xfffffe000a9e2694` | Three arguments serialized into TXM selector 0x34, status decoded as errno-like 16-bit result only for return-code tag 0x2b; caller supplies a domain-like table integer and two other values. Private selector definition and nonce/state/ownership semantics unavailable. Not bound to old void two-argument set_nonce. |
| `0xfffffe000b2a170c` | Image4, BL `0xfffffe000a9e2b6c` | One argument serialized into TXM selector 0x35 with the same status decoding. One argument alone does not prove old roll_nonce ABI/semantics. |
| `0xfffffe000b2a1778` | Image4, BL `0xfffffe000a9e2dd0` | Four nonzero argument guards; forwards two buffer/length pairs. Backend allocates/copies both, transfers code-signing ownership, performs TXM selector 0x36 and error-path reclaim/deallocation. Public execute_object takes a different indexed/struct contract; no numeric-selector equivalence is assumed. |
| `0xfffffe000b2a1798` | Image4, BL `0xfffffe000a9e2e00` | Two nonzero arguments (buffer/length); allocates/copies/transfers ownership, TXM selector 0x37 then return/reclaim logic. The authenticated monitor's state/return contract is not supplied by the native non-monitor backend. |

The 0x34/0x35 wrappers allocate zeroed call descriptors, set input counts
3 and 1, mark the observed flag byte, pass the arguments to the same TXM
call helper and decode status. These bytes establish transport shape,
not the meaning of private selectors. The public TXM implementation is
compiled under CONFIG_SPTM and references private
`sys/trusted_execution_monitor.h`/monitor definitions absent from this
public source tree. The current non-monitor implementation explicitly
reports unsupported monitor operations or panics; using it as a successful
monitor implementation would be incorrect and is not done.

## Baseline and implementation choices

The public Apple XNU tags API was checked during this work; its newest
listed source is xnu-12377.121.6, the current selected base. Thus a public
Darwin 26 source upgrade is not presently a demonstrated repair route.
No experiment proves that changing the kernel base is mandatory: fourteen
references above are recoverable with the current actual native input.
The remaining IDL/monitor contracts are real compatibility gaps; changing
a version number alone would not provide Apple TXM/SPTM on this board.

| Route | Required evidence/work | Current feasibility |
| --- | --- | --- |
| Implement the actual interfaces on this base | Proven IDL for the RPC, complete monitor selector definitions, buffer/state/error semantics, real backend and tests | Possible only with additional authoritative interface/backend information; no guessed crypto/nonce success. Any native change requires new link hash and full collision check. |
| Build a real compatibility layer | Demonstrate equivalent older public APIs, safe lifetime/ownership translations and complete error/security behavior | Investigate method/monitor interfaces individually. Parameter reshuffling or fixed success values are insufficient. Flavor 1 already uses a strictly bounded callable contract; flavor 3 remains separate. |
| Move to a matching source baseline | Available matching source, ported board patches/archives/ABI checks, compatible monitor backend | No matching newer public source was found. Even matching source does not itself supply the hardware monitor. Replacing families/OS would be a separate compatibility project; not performed here. |

No module is dropped, no allow-missing option is enabled, no checker is
relaxed and no final success status is produced for the five unresolved
interfaces. DATA remains 0x1e8000 and must still pass the production
collision check on each real emission.

## Verification before the M4 retry

On the downloaded actual M4 input triple, the new pre-emission evidence
checks pass. A real local invocation of the pinned formal emitter, with
all original roots and strict flags, reduced missing references from 19
to 5. `candidate_written=false`, `mapping_complete=false`, `stubbed={}`.
No XNU compilation or native link was invoked. M4 validation is dispatched
only after this actual binding improvement, and its result is recorded
with the next evidence entry.

## Actual M4 verification

[Run 43140643800](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43140643800)
executed commit `410da46db04af6be5678478968b518abb4cf8854` on UniXNU-M4.
The evidence guard passed on all 13 reviewed functions (two prior, eleven
new) and both typed data objects, including the BASIC_INFO-only contract
and real Image4 storage bounds. Formal strict emission then rejected
exactly the same five unresolved pointers listed above: **19 -> 5**.
No stubs, incomplete publication or native/reference rebuild occurred.

[Recorded result](m4-prelink-recovery-result.json) includes the exact input
digests, reviewed fixture digest, layout, missing targets, ABI guard
receipt and relocation counters. DATA remains
`[0xfffffff00b834000,0xfffffff00ba1c000)`, size `0x1e8000`, with the first
retained Libm byte at its exclusive end: no overlap, zero growth headroom.
The emitter relocated 111,618 native chain sites, kept 130,884 kext chain
sites, rebound 81,130 kext pointers and 561 original adapter branches.

The final failure JSON SHA-256 is
`e52cceee6253cb9b5c5d2e3839fb39544449db1d20bc208fe0f51c1659f1fa31`.
`candidate_written=false`, `mapping_complete=false`, `stubbed={}`. There
is no qualified final prelink image or artifact hash. Failure directories,
map, headers, archives and object caches remain under the existing Mac
persistent root; logs/artifacts identify this run and attempt.

Initial dispatch was rejected because GitHub automatically disabled the
fork's workflows, although repository permissions still said enabled and
package state was active. The GitHub Actions page's fork re-enable action
restored the existing workflows; the authorized prelink dispatch then
ran. Package and smoke jobs were skipped, and no scheduled workflow was
introduced.

Checks also passed locally: Python syntax, workflow actionlint and all 17
structured porting areas. Negative evidence checks rejected an attempt
to treat the native assertion flag as zero and a changed processor_info
closure. Final runtime qualification, new flavor 3, the five unresolved
IDL/TXM interfaces and device boot remain unverified.
