# M4 XNU and CoreCrypto compilation

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
