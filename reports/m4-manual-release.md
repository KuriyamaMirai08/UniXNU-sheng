# Manual private full package on UniXNU-M4

The M4 job now calls the unchanged `scripts/package.sh` -> `unixnu release`
full entry. The seed-free fetch/check/kernel-only sequence is no longer the
M4 entry. Compiler recipes, prelink allow-missing/regression policy, release
order, packing and verification are not changed. No build is dispatched by
this configuration change; the user must click Run workflow.

## Configure Secrets, not workflow inputs

Repository Settings -> Secrets and variables -> Actions -> Repository secrets:

| Secret | Required value |
| --- | --- |
| `UNIXNU_UNIQUE_CHIP_ID` | Existing device identity Secret; this name was already present. Use the actual eight hexadecimal digits for this installation. Its value is not read back by this change. |
| `M4_DATA_SEED_SHA256` | SHA-256 of the user's **original** data.dbr, computed on a trusted machine. Required for either transfer method. |
| `M4_DATA_SEED_URL` | Optional temporary HTTPS URL granting read access to that exact original Seed. Needed only when the private local Seed is absent. Use a private/presigned read-only URL, not a public object or workflow_dispatch input. |

Never put the identity, Seed bytes, Seed hash or private URL in the public
Run workflow fields, repository files, issue comments or public logs.
GitHub's [Secrets instructions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
explain repository Secret configuration. Only Secret names were inspected;
no sensitive value was retrieved or configured by this change.

### Option A: private SSH/SFTP transfer

On the M4, as the same account running UniXNU-M4:

```sh
umask 077
private="$HOME/Library/UniXNU-sheng-private"
mkdir -p "$private/inputs"
chmod 700 "$private" "$private/inputs"
```

Use your existing private remote-management/SFTP connection to place the
original file at `/Users/a105/Library/UniXNU-sheng-private/inputs/data.dbr`.
Do not overwrite a different existing Seed. Set file permissions to 400
(read-only for the runner owner). The file must belong to the runner account.
Set `M4_DATA_SEED_SHA256` to its known original hash. No URL Secret is needed.
The workflow checks owner, type and full digest before using the file.

### Option B: private HTTPS transfer

Store the original file in private HTTPS storage and set its temporary,
read-only signed URL in `M4_DATA_SEED_URL`; set the original file hash in
`M4_DATA_SEED_SHA256`. The URL must remain usable through the initial source
checkout/input preparation. Redirects must remain HTTPS. The existing
64 MiB HTTP transfer bound is retained; larger files can use Option A.

Download occurs only if the canonical private Seed does not exist. It goes
to an owner-only temporary file and must match SHA-256 before atomic,
no-replace publication. Partial/mismatched downloads remain private for
inspection. An existing different Seed causes failure, never replacement.
The canonical original becomes read-only and its digest is checked again
after package.sh returns. No --init-data, Seed regeneration or automatic
replacement is used. The source file/object and existing runtime Seeds are
not deleted.

## Manual operation

1. Actions -> package -> Run workflow.
2. Branch `codex/fix-package29-weak-binds`.
3. `runner_location=UniXNU-M4`, OS `27` for the verified cache/installation.
4. Leave `init_data=false`, `data_seed_url` empty and `data_seed_sha256` empty.
   These legacy fields belong to the hosted flow; nonempty values are still
   rejected before an M4 job is assigned.
5. Click the final Run workflow button yourself.

The build passes device identity through a restricted child environment,
not a CLI argument or committed config. The original Seed is supplied with
the official `--data-ramdisk` option. The empty per-run build config prevents
ignored private unixnu.local.toml overrides. Transport URL/hash, personal PATs and ambient runner-runtime credentials are
not forwarded to the release child. Like the original hosted flow, the
authorized source downloaders receive only the current job's ephemeral
read-only GITHUB_TOKEN; no personal access-token Secret is needed.
Public source fetching uses an empty credential helper. Firmware submodules
are prepared as in the original hosted checkout.

## Persistent compilation and private state

The existing cache root remains
`/Users/a105/Library/Caches/UniXNU-sheng/public-xnu-v1`.
Its name is retained for compatibility, but its top directory is now owner-only
(700), and no part of the M4 job uses actions/cache or uploads artifacts.
Do not reuse historical public-log workflows against this now-private cache.

XNU objects, CoreCrypto objects/archives, board archives, generated headers,
SDK/fakeroot, comparison kernel, sources and verified downloads keep their
existing paths. No clean target, git clean, hard reset or disposable build
tree is introduced. Existing source-pin checks and reviewed cache adapters
remain. A different real Data volume UUID can cause the official runtime
step to update configuration and rebuild affected kernel inputs; preserving
cache is not a promise to keep the previous kernel hash.

Sensitive runtime, payload, boot, kernel-output and pipeline-log directories
are moved (not deleted) into `~/Library/UniXNU-sheng-private/state/...` and
linked from their original official locations. The official Context resolves
the active OS/config output path. Manifest is likewise stored privately.
Existing conflicting source/destination state is preserved and fails for
manual review. An existing runtime Seed is retained and must match the
expected original; otherwise the run stops. The private runtime Seed link
also prevents older seed-free entry points from treating this installation
state as public.

The private parent directories are 700; original Seed is 400; run output
copies are 600. Compiler paths are not moved. The surrounding cache/private
parents restrict access even if an official tool creates a less restrictive
intermediate file. These are same-account filesystem permissions, not
protection against the machine's administrator/provider.

## Results and failures

For run ID RUN and attempt ATTEMPT:

```text
/Users/a105/Library/UniXNU-sheng-private/runs/RUN-ATTEMPT/
  checkout.log
  console.log
  build.toml
  artifacts/                 # created only after successful release/verify
    boot.img
    payload.img
    kernel.macho
    package.manifest.json
```

Use your private SSH/SFTP access to retrieve files. Full pipeline logs and
failure directories remain in private state; compile outputs remain in the
persistent cache. Nonzero package.sh status stops the job, without an outer
retry. No flashing command is run.

All M4 command output is redirected to private files before sensitive input
processing, including exceptions and the author's identity/hash logging.
GitHub receives only generic job status and a private-retrieval notice.
There is no M4 log artifact, plaintext image artifact, Seed backup artifact
or shared GitHub cache. Public repository
[artifacts are downloadable by signed-in users with repository read access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts),
so they are not used for this private M4 delivery. The hosted backup job is
unchanged and does not read the new M4 Seed Secrets or M4 filesystem state.

Failure logs can contain device identity, derived UUIDs, Seed hashes or a
private URL from a transport exception. Share only a redacted relevant
excerpt for diagnosis; do not upload the raw log/state bundle publicly.

## Verification scope

This change receives static workflow/Python/Bash/official-CLI parameter and
privacy-boundary checks only. No Actions dispatch, complete package, automatic
retry, private input transfer or device boot is performed by the agent.
The previously user-run kernel/prelink success is Actions 43146727137;
complete packaging with these authorized inputs awaits the next manual run.
