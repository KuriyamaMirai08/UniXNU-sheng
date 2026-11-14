# Clean kernel B1 experiment

Unattended repair round 2 completed the full clean kernel build in
[run 43615501493](https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43615501493),
using experiment commit 0f16f7de8ddf583458967d1a7239c8b101542bfe.
The downloaded archive then passed offline static acceptance.
The build ran on a new standard GitHub-hosted macos-26 ARM64 VM. It did not run
on M4, restore project objects, or build installation images. The output uses
the profile's existing experimental policy: two unresolved closure references
and nineteen stubbed entries remain. Runtime compatibility is unqualified.

Run 43606241244 compiled XNU from fresh checkouts at device 1281f0f4 and framework
97437dcf. It stopped at the bootstrap link with 12 symbols supplied by later
archives. The attempt archive SHA-256 is
0c698052005c27a937fbf7c4bd75d74f2428af524471b2544cb3373145f0bc2a.

The experiment branch uses the registered prebuild-audit.yml manual entry.
No source pins, compiler targets, final linker options or prelink policies change.
The original framework expects bootstrap link failure before building archives.
The observer now permits only the reviewed exact symbol set, no preceding
compiler errors, the expected LD target, and fresh complete filelist objects.
All other failures stop. JSON evidence records the guard's decision.

Local tests cover the real prior log, injected compiler errors, unknown symbols,
other linker errors, wrong bootstrap mode, missing/stale objects, retained patch
trees, retained prelink candidates and child exit recording. A subsequent run
must use a new hosted VM and may not restore objects from the previous attempt.
Complete compilation, final link, prelink and device boot were unverified at
that point. The later clean result is recorded below.

Run 43607616395 accepted the precise bootstrap failure, then compiled both
CoreCrypto variants from 529 C sources each. Display archive 19 stopped when
the helper path resolved to current/scripts instead of current/UniXNU/scripts.
The isolated sibling output directory exposed the fallback's layout assumption.
Its original attempt SHA-256 is
c2ab436f3440b59a08b4c557c05adbe8c099df365f4b719e5c34af3afa2896df.

The harness now explicitly exports the verified framework and device paths.
It checks the source-driver helper stays in the pinned framework and matches
its recorded SHA-256 before running compatibility, fetch or compilation.
source-paths.json records these inputs. scripts/repro/test_paths.py checks
child-process inheritance, a missing or changed helper and an external symlink.
Each subsequent attempt starts with a new hosted runner and empty project
objects. Original errors, repair diffs, validation and artifacts are retained.

Unattended repair round 1, run 43614112246, passed all three path regressions
on macOS, including the external-symlink case. Source-path evidence identifies
the intended helper. The build then stopped before compilation while restoring
DriverKit crypto headers: GitHub's anonymous contents API returned HTTP 403,
rate limit exceeded. Its complete attempt SHA-256 is
173962b97b4a6d3ad6d5bd7be5badb8e43ba77161f3df6a8614a5ef8e07caede.

Both experimental workflow entries now pass the job's contents-read token to
the isolated build step, as the package workflow already does. The pinned
prepare-xnu-source.py sends it only to GitHub API/raw hosts. Header source tags
and Git blob verification are retained. The token is absent from process
arguments and evidence records. No project objects are restored for round 2.

## Round 2 result and static acceptance

The attempt fetched device 1281f0f4 and framework 97437dcf, recorded their
recursive submodules, resolved the source lock, and applied all 92 ordered XNU
patches. The precompile object inventory was empty. Both CoreCrypto variants
compiled 529 sources with zero failures and 529 object ABI audits. All twenty
ordered component/archive steps completed, including display, source input,
USB, Wi-Fi and Bluetooth integration, and the isolated RELEASE/LTO comparison.
The normal final native link succeeded with no undefined symbols.

The full attempt archive is 736,593,088 bytes and contains 70,690 entries.
Its SHA-256 was checked after download:
76f8549e40c2657ec71149b82b83c696d3ccfeefcc00d8742e409cad67d5a01b.
Original logs, source files, objects, archives and reports are retained in it.

| Output | Bytes | Original SHA-256 |
| --- | ---: | --- |
| Native prelink input, `.unstripped.noctf` | 28,212,032 | `2d1071d451f27bcd330a688a2579bd789b9c5795b1d5e670239850629ec665d9` |
| Native sealed `.unstripped` | 28,212,032 | `64105d26fc5b843151bada3d8e91180bdbbe0602cf64e1810b9b745f31e6eb1a` |
| RELEASE/LTO comparison | 15,969,640 | `de0d880fdcfedad4e47ab0e03f8bcfa0947f78ae58f057ceaf87fed892629aac` |
| Final `kernel.macho` | 96,649,216 | `4c8a0e7e9c786aa95bc7bafd8b938ea0db2866b33d3d888be5e0362b460a70a4` |

Offline acceptance checked archive/product hashes against the runner inventory,
2,074 XNU compile records, fresh link filelist inputs, arm64e native executables,
and the final fileset's segment/section bounds, member mappings and 242,499 root
fixup sites. Its 49 file-backed entries represent a 57-entry dependency closure
including codeless entries. The final native member has no undefined symbols.
Its relocated CoreCrypto HMAC matches a fresh calculation over emitted code.
The official sealed native output's HMAC also matches its actual instructions.
The `.noctf` prelink input is the original unsealed link output; the existing
fileset emitter reseals the relocated output. No candidate bytes were changed
during offline acceptance.

Clang's 52 assembler-with-cpp compile records name temporary preprocessing `.s`
outputs. Acceptance reconciles them with the corresponding fresh `.o` files,
recorded AS steps and final filelists. Host SETUP objects and generated genassym
assembly text are distinguished from target inputs. All 2,070 inputs across
the native and RELEASE/LTO filelists are arm64e relocatables or LLVM bitcode.
The Python observer recorded 1,349 compile spawns and successful exits; native
make's child commands additionally rely on compile records and build logs.

The comparison builder retains its pre-existing behavior: it generates two
diagnostic placeholder globals, `boot_cache_input_capture` and
`native_source_storage_start`, and omits 67 unavailable forced exports from
its private source copy after the initial comparison link returns exit 2.
The subsequent comparison link returns exit 0; both outcomes and the omitted
export list are retained. This behavior is limited to a layout/symbol comparison
input and cannot qualify a runnable kernel. The real DEVELOPMENT link uses
the original required archives. This repair did not add placeholders or allowances.
Mixed arm64e ABI flags occur in the existing firmware-data and assembly-binding
members; native relocation and all 561 original branch adapters passed.

The original Apple kernelcache SHA-256 is
38e6d9fa5f789b8228f4617ef4c6d2a3fd8ab564abdc9b62920f1db53fc1780a.
The effective regression policy matches the unchanged pinned framework file.
The final report records two missing sites, nineteen stubbed entries and 163
rejected double-bind candidate pairs. `mapping_complete`, `loadable` and
`runtime_qualified` remain false. One complete clean build proves construction
from the recorded inputs; it does not prove byte-for-byte reproducibility,
strict zero-gap prelink, CoreCrypto runtime selftests or successful device boot.
No device operation was performed.

## Recorded inputs and historical comparison

The kernel stage took 1,211 seconds in the 26 minute 25 second job. The runner
recorded macOS 26.7.2 (25G332), image 20261102.0473.1, three cores, 7 GiB RAM,
Xcode 26.6 (17F113), Apple clang 21 (clang-2100.1.1.101), iPhoneOS SDK 26.5 and
iOS deployment target 27.0. Homebrew LLVM/LLD was 23.1.4, Python 3.15.2 and
Rust 1.98.0. Runner tool versions are recorded inputs, not a fully frozen SDK
or package installation.

The resolved source lock selected XNU ac9718fb1af618d5ce8678d0dc6e8a58f252216f
(12377.121.6), SM8550 97665e28578483082b674e8375a8fa65f4cf49cf and CoreCrypto
11fba65b12d8830630e248dfa8344caf8b065f26. Recursive gitlinks, original and
resolved locks, actual compile commands, patch digests and experiment framework
transforms are preserved in the archive. The target was arm64e using
sheng_ipados27_defconfig and the 4,096-byte profile page size.

The recorded author A0 baseline is device
82d9e23ade933aa9d6c9ea2f4f40045e2d985479 and framework
82b847c4ac3f68a57024b3082ffa3a03442defd9. It selects the same XNU pin but 87
ordered patches; the current input selects 92 and changed driver/tool gitlinks.
This session did not build A0 or obtain its binary. Historical M4 run 64
reused XNU, CoreCrypto and comparison objects; its log reports a 96,649,216-byte
fileset with two missing references, nineteen stubs and SHA-256
4b56a12f1bf287a4f3c6d7538a6bd0edfae7fe9e25cb35696a325e15846498c8.
The current hash differs. Equal sizes and matching summary counts do not prove
binary equivalence or identify a device boot failure. Both recorded board
versions set vmm-present=1, so the early PMGR return also prevents treating
pmgr=0 alone as proof of inevitable startup failure.
