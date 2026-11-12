# Manual official release on UniXNU-M4

Only a user workflow_dispatch starts package or prebuild audit. The package
form selects `runner_location=UniXNU-M4` or the existing `hosted` path.
Standalone smoke/compile/native-link/strict-prelink choices were removed
from this form. Only the existing official CLI commands are used; no new build tool is introduced.

## Run from GitHub

1. Actions -> package -> Run workflow.
2. Select branch `codex/fix-package29-weak-binds`.
3. Select `runner_location=UniXNU-M4`, OS `27` for the existing cache.
4. Leave `init_data=false`, `data_seed_url` empty and `data_seed_sha256` empty.
5. Click Run workflow yourself. On failure, download `m4-release-logs-<run>-<attempt>`.

The self-hosted job matches the default macOS ARM64 labels and refuses any
runner whose name is not exactly UniXNU-M4. No dedicated extra label is
required. Concurrent M4 releases queue rather than cancel the active build.
Choose `hosted` for the existing GitHub macOS job and its original image /
installation input flow. The hosted job definition is unchanged.

## Persistent state and compatibility

The M4 root stays `/Users/a105/Library/Caches/UniXNU-sheng/public-xnu-v1`.
Source checkout, outputs and ignored files stay outside the runner workspace;
there is no actions/checkout, git clean, hard reset, clean target or disposable
per-run build tree on the M4 path.

- `device`: the manually selected PR revision and its component checkouts.
- `UniXNU`: existing pinned `97437dcf7389484a0eeaa8067725ce743aff18ef`.
- `uefi-sheng`: public source pinned `66421cb7bb5694843aec8de1ca3d1de4c20cca38`.
- `out/feeds`, `out/ipsw`, device `.cache`: source and verified download caches.
- `out/sheng/<OS>/<config>/tree/build/xnu/ios-obj`: XNU objects/compile records.
- That same tree's `.cache/fakeroot`: generated Kernel.framework headers / SDK.
- That tree's `build/corecrypto-2023` and other `build/` directories: CoreCrypto,
  board archives, comparison kernel, tools and other reusable build output.
- `logs/<run>-<attempt>`: checkout, complete release console and copied pipeline logs.
  GitHub keeps the public log artifact for 14 days; the Mac copy is persistent.

Base revisions are checked before reuse, and unknown source edits stop rather
than reset the checkout. OS/config outputs retain their existing separate paths.
Source changes arrive through the normal persistent PR checkout. The official
release regenerates its defconfig/patch inputs and runs its own dependency,
command, source and output identity checks. Keeping an object does not make an
incompatible object valid.

Only the known standalone forced-bootstrap condition is normalized back to the
existing hosted header-bootstrap fix. The proven existing cache-aware CoreCrypto
builder and GPU network retry are accepted if already installed; unknown variants
are refused. The existing prepare-package-ci.py compatibility fix remains in use.
The extra M4 reviewed-symbol fixture is moved to `retired-stage-overrides`, not
used by release. No object, archive, header or failure log is removed for this.
Official prelink parameters, allow-missing behavior and regression checks are
not replaced by the previous strict standalone entry or its evidence guards.

Incremental behavior still depends on the author's scripts: archive recipes may
run on each release; an unmodified CoreCrypto builder may recompile its batch;
Make may relink or rebuild when dependencies, flags, patch inputs, generated
headers or toolchains change. Comparison builds have their own identity checks.
The workflow does not suppress these rebuilds or declare retained outputs current
without their normal checks. A missing/incomplete SDK header cache may force the
existing bootstrap repair. Official scripts may intentionally replace their own
generated intermediates or delete extracted download archives.

## Rental-Mac installation boundary

The M4 job receives no repository secret, PAT, seed cache or seed URL. Nonempty
installation dispatch inputs are rejected in a separate hosted job, before a
job/event file is sent to the rental Mac. The release subprocess gets an explicit
public environment and empty `[build]` config, so it does not inherit credentials
or private `unixnu.local.toml` build inputs. Existing installation seed files and
local source overrides cause a stop; they are not consumed or uploaded. Only
public logs, not runtime directories or old image files, are uploaded.

The M4 job uses the official CLI's existing independent commands, sharing
`--os`, `--uefi`, `--out`, `--config` and `-j 4` options:

```sh
python3 "$M4_ROOT/UniXNU/unixnu" fetch "${args[@]}"
bash scripts/package.sh "${args[@]}" --no-deps --check
python3 "$M4_ROOT/UniXNU/unixnu" build kernel "${args[@]}"
```

`fetch` prepares the same source dependencies as release's source-fetch step,
without a bulk IPSW fetch. The unchanged package.sh calls `unixnu release`
with its existing `--check` option: it generates the selected defconfig and
resolves/lists the ordered patch series, then returns before runtime preparation.
The official kernel builder applies those patches through its normal recipe.

In pinned UniXNU `97437dcf7389484a0eeaa8067725ce743aff18ef`,
`scripts/unixnu/cli.py:cmd_build` calls runtime.prepare only when `payload` or
`runtime` is selected. `build kernel` selects neither: it runs the actual
kernel.build followed by kernel.prelink. XNU, CoreCrypto, archive dispatch,
native link and prelink validation are unchanged. No skip-prelink flag or
altered allow-missing/regression policy is passed. A compiler or prelink
error stops the job normally and retains the existing caches and logs.

After successful kernel/prelink, the job explicitly stops before
runtime/payload/boot packaging. A green M4 job qualifies only these public
kernel commands, not a complete package or boot.img. The full official
release still needs the original Data seed before its combined build, and
payload ADT later requires the actual unique-chip-id. Those installation
inputs remain unauthorized on the rental Mac. No fake identity, generated
seed, validation bypass or private-interface development is included.

## Configuration-only validation

This change is validated without dispatching a build. Checks cover actionlint,
embedded Python/Bash syntax, manual-only build triggers, hosted-job preservation,
job-selection/input isolation and the structured porting record. The official
CLI parser and command-dispatch source were also checked for the seed-free
command sequence. Actual execution and subsequent real errors are
left for the user's next manual run.
