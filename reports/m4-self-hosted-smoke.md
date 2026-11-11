# Mac mini M4 public-source smoke

In Actions, select **package**, **Run workflow**, branch
`codex/fix-package29-weak-binds`, and `runner_location: self-hosted`.
Leave `init_data` unchecked and both seed fields empty. The OS selector is
ignored by smoke. `hosted` preserves the existing device-bound package path.
Do not run a hosted package merely to test the M4.

## Isolation and routing

`m4-smoke` uses `[self-hosted, macOS, ARM64]`, then checks that `runner.name`
is exactly `UniXNU-M4` before checking out or compiling anything. No custom
label setup is needed with the currently registered single matching runner.
If another ARM64 Mac is registered, GitHub may assign that runner and the
name guard will fail without building. In that case add a unique `UniXNU-M4`
label in Settings > Actions > Runners > UniXNU-M4 and add that fourth label
to this job's `runs-on` before dispatching again. A runner name by itself
is not a scheduling label.

The smoke job has `permissions: {}` and uses anonymous public git clones,
not actions/checkout or authenticated API calls. It never references a
secret, PAT, `github.token`, Actions cache restore/save, artifact upload,
release/package command or device firmware download. Sensitive dispatch
inputs gate the job off before assignment; an Ubuntu job reports rejection.
Never paste a real seed URL into a self-hosted dispatch. The name guard is
a routing check, not proof that a rented host is trustworthy.

All existing sensitive operations stay in the hosted-only `package` job:
`platform seed`, `seed cache identity` and `package` reference
`UNIXNU_UNIQUE_CHIP_ID`; `prepare preserved Data seed` reads the seed URL;
Data cache restore/save and `installation seed backup` handle `data.dbr`
and `inputs.json`; image uploads deliver the device-bound outputs. There
is no dependency or artifact/cache transfer from that job to smoke.
Hosted installation-seed caching/backup behavior is unchanged. Existing
Actions caches are not imported to the rental Mac, including the broad
heavy cache, which cannot be assumed to be free of device-specific inputs.

## Persistent paths and actual build scope

The absolute root is
`$HOME/Library/Caches/UniXNU-sheng/public-smoke-v1`:

| Path below root | Use |
| --- | --- |
| `src/UniXNU` | Public source pinned to `97437dcf`; reused without reset/clean |
| `src/uefi-sheng/Mu_Basecore` | Pinned EDK sources and built BaseTools, including `BaseTools/Source/C/bin/GenFw` |
| `edk-package/Build/UniXNU/DEBUG_CLANGPDB` | Actual persistent EDK object/output directory |
| `edk-package/Build/Out/AARCH64-DEBUG` | Six standalone EFI files checked after compilation |
| `toolchain` | EDK tool symlinks, refreshed without deleting build output |
| `rust-probe`, `cargo-target` | Stable tiny offline Rust source and Cargo incremental output |

The workflow's temporary device checkout is outside this root. Neither
Actions workspace cleaning nor the anonymous checkout touches these paths.
The pinned `package/build.sh` accepts `UNIXNU_BUILD_DIR`, does not clean it,
copies only absent/newer Conf templates, and builds BaseTools only if GenFw
is missing. Four build workers bound memory use on the 16 GiB M4.

XNU is **not compiled by this smoke**, and no claim of a reused XNU build
or successful full kernel relink is made. Path review of the pinned source:
the normal profile output is `UniXNU/out/sheng/ipados-27.0.1-24A446/`
`sheng_ipados27/tree/`; expensive paths beneath it are
`build/xnu/ios-obj`, `build/xnu/fileset-reference`, `build/m2v-target`,
`build/mesa-tu-ios27`, `.cache/fakeroot`, and `.cache/appsync-signer`.
`scripts/unixnu/tree.py:assemble` retains `build` and `.cache`; it refreshes
module links and changed script copies. A future public-only kernel test
using this persistent `src/UniXNU` will retain its `out` across dispatches;
this change does not add that kernel test or populate/import those caches.
Never run a real seeded release in this cache. Existing workspace XNU
output is left untouched; it is not migrated or advertised as reused.
The CoreCrypto Kernel.framework header-bootstrap fix remains unchanged.

No duplicated Actions cache archive or multi-gigabyte firmware is fetched.
There must be 20 GiB free before compiling; no automatic pruning occurs.
The root is shared across branch dispatches under a workflow concurrency
group and an atomic directory lock. After interruption, confirm no build
is active before removing only the empty `.lock` directory. Keep sources
and tools unchanged for incremental reuse. On compiler/source upgrades,
review cache validity and intentionally choose a fresh versioned root or
clean only the affected build directory; do not routinely delete all output.

## Prerequisites and limits

The test checks Xcode 26.6 / 17F113, iPhoneOS SDK, Python with `tomllib`,
the hosted workflow's Brew formula/tool list, Rust 1.98.0 and rust-src.
It reports missing dependencies without upgrading the machine. If needed:

```sh
brew install dtc llvm lld cmake mtools ninja glslang shaderc spirv-tools bison pkgconf rustup blacktop/tap/ipsw
rustup toolchain install 1.98.0 --profile minimal --component rust-src
```

Only the EDK Mu_Basecore and three needed nested submodules are fetched.
The six standalone EFI outputs, offline Rust probe, and real board kcpu
helper's sanitizer/arm64e compile tests exercise compilation without an
IPSW, stock ROM, real seed, complete XNU kernel, or platform FD. Passing
does not establish full package feasibility or successful device boot.
Run smoke a second time to observe EDK/Cargo incremental reuse. A rented
host can falsify its own logs; this is a functional check, not attestation.
