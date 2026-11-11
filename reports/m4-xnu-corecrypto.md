# M4 XNU and CoreCrypto compilation

## Native-link stage

The next stage is `self_hosted_stage=native-link`, also using `os=27` and
empty installation inputs. It runs the original ordered production
`kernel.build_archives` and final native make, with no narrowed archive
dispatcher and no forced bootstrap when retained records/headers exist.
Both CoreCrypto recipes retain dependency-validated object reuse. The
previous environment initialization checks are not repeated in this mode.
The already-installed Rust 1.98.0 compiler directory is put on PATH for
production Cargo recipes without relying on optional rustup proxy shims.

Sources, headers, archives and object directories stay under the same
`public-xnu-v1` root. Each attempt saves the actual production archive plan
and full per-recipe/final-link logs in its own log directory. Failed jobs
do not remove successful outputs. The pinned Ath12k fetch compatibility
transform used by hosted packaging is applied without source pin changes.

A native-link success requires the real build command to succeed and
the selected kernel output to be an arm64e `MH_EXECUTE` with no undefined
symbols reported by Apple nm. Its SHA-256, byte size, architecture and
archive inventory go in `native-link-report.json`; Apple otool and size
load-command/segment reports are saved alongside it. No link-only error
filter is used for this stage. Prelink and all installation operations
remain excluded.

Run 43062836814 reached source-storage, RamBlock, the Adreno740 base archive
and DTS generation. It stopped reading a pinned GPU input with a network
timeout. CoreCrypto reused 529/529 objects in both variants. A retry also
exposed the checkout guard rejecting the known Ath12k fetch compatibility
edit left by the preceding build. The guard now validates that exact
tracked edit and rejects other submodule edits, without resetting source
or deleting outputs. GPU input transport gets bounded retries and a
longer read timeout; all content hashes, lengths and Git blob identities
remain checked before writing retained files.

Run 43063685115 passed the pinned GPU input checks, GMU/SMMU preparation,
Adreno kit/accelerator builds and AppleKeyStoreState, then exposed a
display-builder path assumption: `ROOT.parents[4]` was assumed to be the
UniXNU checkout. The persistent `--out` root is outside that checkout.
Native mode now supplies `UNIXNU_ROOT` explicitly and the board display
builder uses it to locate the unchanged shared source-driver helper and
its OS profiles. No archive/ABI validation is removed.

Run 43064254937 resolved the shared helper correctly and exposed a missing
IOHIDFamily source checkout. `cli.prepare(kernel)` fetches the bootstrap
reference subset; the production board archives require additional pinned
references. Native mode now performs the source-only `feeds.fetch` part of
normal dependency preparation before the original archive dispatcher.
It respects the same source pins and existing checkouts; IPSW/runtime/Seed
preparation remains excluded.

Run 43064681233 fetched the missing references and advanced through the
display source-driver/ABI work to the keyboard firmware prerequisite.
Native mode now uses the existing SHA-256-checked `extract-files.py
--section Keyboard` and the same Wi-Fi/Bluetooth source prefetch commands
as hosted package preparation. The public keyboard image is 82,524 bytes;
no stock-ROM archive, installation runtime or Seed is involved. Source
prefetch is outside the display sub-build's compile timeout; its existing
compiler/object checks and pinned-source preparation remain unchanged.

Dispatch `package.yml` on `codex/fix-package29-weak-binds`, with
`runner_location=self-hosted`, `self_hosted_stage=xnu-corecrypto`, `os=27`.
Leave seed fields empty and init_data false. This selects a separate job;
neither the earlier EDK smoke nor hosted packaging runs.

The persistent root is
`/Users/a105/Library/Caches/UniXNU-sheng/public-xnu-v1`.
It holds `device`, pinned `UniXNU`, source feeds and `out`. Updating the
device checkout does not run git clean/reset or remove ignored outputs.
The root has a fail-closed atomic lock; cancellation can require inspecting
the lock and removing only that empty directory after the process stops.
Every attempt has independent `logs/<run-id>-<attempt>/` console/pipeline
logs and reports, uploaded as public compilation logs, never seed files.

For the selected profile the tree is
`out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree`:

* `build/xnu/ios-obj` retains real XNU objects and compile records.
* `.cache/xnu-work` retains the prepared/patched XNU source.
* `.cache/fakeroot/System/Library/Frameworks/Kernel.framework/Versions/A`
  retains generated public/private headers including `kern/clock.h`.
* `build/corecrypto-2023` retains plain/namespaced objects, archives,
  per-source diagnostics, clang depfiles and successful-object identities.

The existing pinned header-bootstrap fix from `prepare-package-ci.py` is
applied unchanged. This stage additionally runs the real XNU bootstrap
make on every retry, so an old startup record cannot hide incomplete XNU
compilation. The existing production sheng iPadOS 27 config, version
environment and ordered patches are used. Four workers bound memory use.

The process uses the existing `kernel.build` bootstrap path, then narrows
its in-process archive dispatcher to the two actual CoreCrypto builds.
It stops there: other board archives, final native kernel link, prelink,
firmware, runtime/Seed and installation images are not run. The initial
bootstrap may stop at its intentionally unresolved archive link; C/C++
compiler errors remain failures and are not accepted as link-only errors.
Passing this stage is not evidence of a complete native kernel link.

CoreCrypto's pinned builder gets an exact scoped transform: successful
objects are reused only if command/compiler identity, all clang `-MD`
dependencies (including SDK/generated headers), and the object hash still
match. Failures preserve earlier objects and per-source logs, but are not
accepted as current success. Archives retain the original object/ABI and
symbol-survey checks. No bulk cache cleanup occurs; the existing XNU
script may selectively invalidate individual objects when its inputs change.

The rental runner receives no repository secret, PAT, device identity or
installation Seed. Public sources are fetched anonymously. Logs and
objects stay on the Mac even if a job fails or an artifact upload fails.

## First real build observation

Run https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43057794006
fetched the pinned sources and applied the production patch series. The
header-bootstrap check correctly detected missing `kern/clock.h` and ran
XNU `installhdrs`. The subsequent firehose Xcode build stopped with code
70 because `/Library/Developer/PrivateFrameworks/CoreSimulator.framework`
was absent; Xcode's IDESimulatorFoundation plugin could not load. The M4
could answer `xcodebuild -version` and run clang, which did not expose this
system-component problem in the earlier EDK smoke.

The workflow now runs the official `xcodebuild -runFirstLaunch` when system
components are incomplete, using noninteractive sudo if available. It never
requests or stores an admin password. If admin setup is blocked, the exact
local administrator command is printed. Existing sources/headers/outputs
are retained and the next dispatch resumes in the same persistent tree.

After administrator initialization, attempt 2 of run 43059188516 reused
the source/header tree, compiled XNU to the expected unresolved bootstrap
link, and confirmed all three required Kernel.framework headers exist.
The stage then incorrectly rejected `clang++: error: linker command failed`
because its link-only filter accepted `clang` but not `clang++`. It now
accepts either driver only when the log also contains the arm64e undefined
symbol diagnostics. Source compilation errors still fail; other board
archives and the final native link remain deferred in this stage.

## Verified compilation and incremental retry

Code revision: `2267df6cbf50dab923445866c7e75887cad2e604`.

* First successful stage:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43061093667
* Successful incremental stage:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43061503882

Both ran on `UniXNU-M4`, skipped EDK smoke and hosted package, and retained
the same persistent tree. `stage-report.json` recorded 957 XNU `.o` files
and all three generated Kernel.framework headers. XNU source compilation
reached the deliberately unresolved bootstrap link. Ordinary and
namespaced CoreCrypto each compiled 529 kernel C sources with zero
failures; all 529 objects in each archive passed the original architecture
and deployment audit. Neither archive had external names absent from the
XNU object symbol set. The namespaced archive had zero globals shared with
the XNU object symbol set (the plain archive had 64, as expected).

The incremental run reported `CoreCrypto objects reused: 529/529` for both
variants and no XNU CC/CXX/AS compile commands. The compile step took 22
seconds, compared with 70 seconds for the first successful stage. Both
archive hashes were identical across those two runs:

| Archive | SHA-256 |
| --- | --- |
| `libcorecrypto_kernel_noasm.a` | `c376cb840a1a5aab27b02ab14958f3c62e62266e972fe9bd35ab89aa1ea921ad` |
| `libcorecrypto_kernel_noasm-namespaced.a` | `4d74783c8cbbb784301878f4bb8a863c396269d9e4dd2ef129f9908ff897bc2e` |

The actual `kern/clock.h` include chain now compiles successfully. No
cache/header removal or production validation bypass was needed. Full
board archive integration, final native link, CoreCrypto registration and
selftests, prelink and boot are still unverified. The next stage is to
build the remaining production board archives and complete the native
link from this retained tree, without introducing installation inputs.
