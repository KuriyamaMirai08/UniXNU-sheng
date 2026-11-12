# Manual M4 full release and first installation

Use Actions -> package -> Run workflow on branch
`codex/fix-package29-weak-binds`, with `runner_location=UniXNU-M4`, OS `27`,
and `init_data=true` for the first installation. Leave both legacy
`data_seed_url` and `data_seed_sha256` form fields empty.

The only required repository Secret is `UNIXNU_UNIQUE_CHIP_ID`: the actual
nonzero unsigned 64-bit hexadecimal identity for this device: 1-16 hex digits,
with an optional `0x`/`0X` prefix. Keep all high bits and leading zeros from
`/sys/devices/soc0/serial_number`; do not truncate to eight digits. The value
is passed unchanged to the official builder, which encodes it as little-endian
64-bit ADT `unique-chip-id`. Zero, invalid hex and values longer than 16 digits
are rejected. A missing or invalid value produces
a public error naming the required Secret without printing its value.
`M4_DATA_SEED_SHA256`, `M4_DATA_SEED_URL` and advance Seed transfer are not
required by the M4 job.

## Official first-install input handling

With no saved Seed, the workflow calls the unchanged official
`scripts/package.sh --init-data` (with the existing OS, UEFI, output,
configuration and job-count options). It supplies no `--data-ramdisk` in
this case. Official `unixnu release` and its runtime builder generate
`runtime/data.dbr` before the kernel build. No custom Seed generator,
replacement build driver, skip flag or stricter prelink rule is added.
Automatic first-install generation in this workflow is for OS 27.

Once a Seed exists, subsequent runs use `--data-ramdisk` and omit
`--init-data`, even if the checkbox remains selected. Existing runtime
Seeds are reused, never replaced. A local private SHA-256 record detects
later changes; no hash Secret is required. A Seed generated before a later
build failure is retained and reused on the next run. A partial or invalid
Seed is retained for diagnosis rather than regenerated automatically.

The workflow still executes the full official release sequence, including
compilation, official prelink, firmware, payload, boot packaging and
verification. Failures stop the run without automatic retry or flashing.

## Persistent paths on UniXNU-M4

The compiler root remains:

`/Users/a105/Library/Caches/UniXNU-sheng/public-xnu-v1`

Source pins and the existing reviewed bootstrap/cache fixes remain unchanged.
The XNU objects, generated Kernel.framework headers, both CoreCrypto variants,
board archives, tree/build and .cache keep their existing absolute paths.
No checkout clean, build cleanup or GitHub cache upload is added. The new
Data UUID can legitimately require the official build to update configuration
and rebuild affected objects. Other official steps may rebuild according to
their own dependency rules.

Private outputs and logs remain under:

`/Users/a105/Library/UniXNU-sheng-private`

For the OS 27 default configuration:

- Generated Seed: `state/sheng/ipados-27.0.1-24A446/sheng_ipados27/runtime/data.dbr`.
- Stable saved Seed: `inputs/data.dbr` (a hard link to the generated file, not a second copy).
- Local integrity record: `inputs/data.dbr.sha256`.
- Current boot image: `state/sheng/ipados-27.0.1-24A446/sheng_ipados27/boot/boot.img`.
- Current payload: `state/sheng/ipados-27.0.1-24A446/sheng_ipados27/payload/payload.img`.
- Per-run logs: `runs/<run-id>-<attempt>/checkout.log` and `console.log`.
- Successful per-run output copies: `runs/<run-id>-<attempt>/artifacts/`,
  containing `boot.img`, `payload.img`, `kernel.macho` and `package.manifest.json`.

The official output paths are linked into private state; compiler paths are
not moved. Conflicting old/private state is retained and stops the run for
review. Parent directories are owner-only (700); saved Seed is read-only
(400); per-run outputs are owner-only (600). Full logs, manifests and images
are not uploaded as GitHub Artifacts or shared caches. Retrieve them through
your private Mac access. Do not rerun historical public-log workflows against
this now-private build state.

The original hosted fallback is unchanged. This revision received static
validation only; no Actions build, Seed generation or device operation was
started by the agent. The user starts each real run manually.

## Package 65 checkout recovery

Run 43153151789 stopped in checkout preparation before the official release.
Its private checkout.log showed the generated unixnu.lock diff: adding
IOHIDFamily e31e90a24c27ad6cbe981650d12a1a4124065b03 and resolving
IOStorageFamily to 7edb88fbae296fb7c8ce2f64e115e116e566d51c. These match
reports/ipados26-source-drivers.json. The original and retained lock blobs
are e54efdc3f63d94f56660c47bfae0ced6af39810a and
36c2b1847c35ea00dd67733caceff38cc219e07f respectively.

The preparation guard accepts the original lock or precisely that retained
resolution. It preserves the file in place. Unknown lock contents, staged
lock edits, and other tracked source changes still stop preparation. Existing
Ath12k validation, source pins, build cache paths and private Seed handling
are unchanged. No clean, reset, lock rewrite or build command was added.

`python scripts/test-m4-checkout.py` uses local Git fixtures to reproduce the
original exit 1 and verify the repaired
guard, rejection cases and a real checkout transition. Cache and private Seed
fixtures retained their bytes and timestamps. This is not a real M4 build.

After this fix, start a new Run workflow on the PR branch as described above.
Do not use Re-run jobs on package 65: it uses the old commit and workflow.
For an existing saved Seed leave init_data unchecked; first installation
without a saved Seed still requires init_data=true. Leave both URL/SHA fields
empty. The fix itself does not dispatch any workflow.

## Package 66 UEFI checkout scope

The M4 preparation follows board.toml firmware.submodules and the pinned
UniXNU scripts/unixnu/firmware.py: Common/Mu, Common/Mu_OEM_Sample,
Silicium-ACPI and Silicon/Silicium/OpensslPkg/Library/OpensslLib/openssl.
Only these four direct gitlinks are initialized, without recursion. The
official fetch separately supplies edk2/Mu_Basecore and its selected direct
dependencies from UniXNU feeds.toml; firmware preflight imports Binaries/sheng.
The duplicate uefi-sheng/Mu_Basecore and the Binaries submodule do not need
initialization here. Existing copies are retained.

OpenSSL's gost-engine, TLS tests, other test integrations and fuzz corpora
are not inputs of the selected OpensslLib.inf. Preparation no longer traverses
them. Each selected update uses depth 1, one job, HTTP low-speed limits of
1024 bytes/s for 60 seconds, and a 600-second process-group deadline. Timeout
terminates git/fetch/index-pack and stops; it does not delete Git data or retry.
Existing full repositories are reused, not deliberately converted or cleaned.

Local Git fixtures verified shallow direct checkout, disabled recursion even
with submodule.recurse=true, repeat execution and unchanged cache/private/Git
sentinels. A timeout test verified process-group termination and immediate
failure. No full M4 release was run. If package 66 is still active, cancel it
and wait for the runner to stop before starting a new manual workflow on the
updated PR branch. Do not delete lock files or partial repositories while Git
is running. Re-running the old job uses its old workflow revision.
