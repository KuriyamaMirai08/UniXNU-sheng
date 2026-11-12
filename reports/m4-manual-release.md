# Manual M4 full release and first installation

Use Actions -> package -> Run workflow on branch
`codex/fix-package29-weak-binds`, with `runner_location=UniXNU-M4`, OS `27`,
and `init_data=true` for the first installation. Leave both legacy
`data_seed_url` and `data_seed_sha256` form fields empty.

The only required repository Secret is `UNIXNU_UNIQUE_CHIP_ID`: the actual
eight hexadecimal digits for this device. A missing or invalid value produces
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
