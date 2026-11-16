# Boot source audit, 16 November 2026

The existing images are this fork's build outputs, not an upstream author's
published boot image. No downloadable, verifiable 24A446 upstream boot image
was obtained from the upstream device, framework or UEFI release pages, the
device package workflow runs or its retained artifacts. Other upstream
workflows have porting-record runs; those are not boot releases. The comparison source is the verified common ancestor
`82d9e23ade933aa9d6c9ea2f4f40045e2d985479`; it is not a binary release.

The target remains `ipados-27.0.1-24A446/sheng_ipados27`, with a DEVELOPMENT
native kernel, RELEASE-LTO comparison and the original installed binding and
Seed. Framework `97437dcf7389484a0eeaa8067725ce743aff18ef`, XnuPrelink
`8f4f3866545727e2dc3d2c8cb60f8a87a9539c12` and UEFI
`66421cb7bb5694843aec8de1ca3d1de4c20cca38` remain fixed.

## Implementation corrections

The generated LegacyDisplaySupport27.cpp supplied four strong, empty or
fixed-return functions introduced by this fork's package-29 workaround. They
made absent optional providers appear present and hid the GPU pager hook's
absence. Remove those functions. Source guards preserve every actual provider
and the upstream weak-import path by default. The isolated 24A446 build uses
a checked capability header: the two kernel providers are absent from actual
prepared source and the Ethernet/AES providers are only selected in macOS.
An unexpected provider stops the build for a revised capability selection.

The request-layout data is real ABI input. Generate its six values from the
same reviewed 24A446 fixture as the framebuffer, as a strong constant; it is
neither a function placeholder nor another device's identity.

The upstream RELEASE comparison builder synthesized two scalar placeholders
for callable hooks in the existing run. This candidate instead links the real
source-storage, Adreno and display archives built in this same clean run.
Missing real providers fail; no native-stubs.c is generated. Original
reference input hashing, source/SDK identity checks and forced-export evidence
are retained.

The first reference link may stop at unavailable forced exports named as
`<initial-undefines>`. Preserve the author's subsequent object-symbol export
list reconciliation, record every first-link undefined name and require the
final real link to succeed. A control-flow regression accepts the reconciled
export case and refuses publication when the final link lacks a real provider.
Neither test fixtures nor placeholder providers enter the production build.

Run 43747167997's first link also has four real missing dependencies from the
DEVELOPMENT archives: three signed-overflow minimal-runtime handlers and
`mach_assert_jump_key`. XNU's RELEASE configuration does not select those
providers. Its original `san/memory/ubsan_minimal.c` implements the handlers
with real `brk #0xff00` traps, with the telemetry and initialization paths;
`osfmk/kern/debug.c` defines the structured assertion jump key and its feature
override lifecycle. These are not empty fallback functions or scalar substitutes.

Run 38 (43755649212) exposed a configuration error in that first fix.
Global `mach_assert` changes `ipc_port` to 160 bytes while RELEASE requires
144, and enables `os_log_valid` assertions without its debug-only declaration.
The missing `nonltolink.filelist` exception is secondary to those compiler errors.

The private comparison retains global RELEASE assertion configuration. Two
exact guards in the hash-pinned original `debug.c` select the genuine static-key
definitions and their full feature-override lifecycle for the real DEVELOPMENT
archives. Its original UBSan minimal runtime remains selected. No callable or
scalar substitute is generated. Source hashes, the private transformation and
final defined symbols remain in the receipt; strict prelink refuses a globally
changed RELEASE assertion ABI. The native DEVELOPMENT configuration is unchanged.

Five local publication regressions pass, including compiler-exit preservation
before final-link input discovery. Actual Apple compilation, strict prelink and
final boot image acceptance are pending. Documentation run 43755647089 also
found an unowned configuration fixture; the diagnostics area now owns that
fixture directory. No validation check is removed.

## Verification scope

The new check executes the actual guarded GPU and RAM statement blocks with
absent and present test peers, uses Apple's arm64e kernel linker and the
unchanged XnuPrelink parser, and requires a missing enabled provider to fail.
Test peers are never inputs to a native or comparison kernel. Final native
acceptance also requires all four symbols absent and no chained imports or
binds. Strict complete mapping, collision detection, source hashes, real
normal-Image4 branch, HMAC, trust and device binding checks remain required.

Full clean compilation and static acceptance are pending. No device command
is authorized or run by this audit. No author-binary equality or successful
hardware boot is claimed.

The compact artifact retains the 17 guarded prepared source files, all build
logs and inventories, final images, real archive recipes/outputs, runtime
trust inputs and DarwinBoot PE/map/PDB records. It accompanies the complete
build archive. Evidence-only selection never changes compilation or acceptance.
