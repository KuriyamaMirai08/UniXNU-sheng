# Package 29: chained weak-lookup imports

## Failure and provenance

- Failed run: https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/42996277869
- Device revision: `59fd891211ff79ab5047f9d19a80d95e6a3b29a7`.
- UniXNU revision checked out by that run: `97437dcf7389484a0eeaa8067725ce743aff18ef`.
- Start: 2026-11-11 09:34:12 UTC; completion: 10:35:01 UTC (60 minutes 49 seconds).
- Uploaded archive: `build-logs-27 (5).zip`; its `prelink.log` agrees with the full Actions log.
- Native executable recovered without rebuilding from cache `unixnu-heavy-build-27-59fd891211ff79ab5047f9d19a80d95e6a3b29a7`.
- Native SHA-256: `6fddf022b48fbf1e73a9ce60738607e3f08377938ed904a6792595c40a7550f8`.
- Cache recovery run: https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43009682891

The bootstrap pass fails to link before the archive builders run. This is
explicitly tolerated in `scripts/unixnu/kernel.py` once the required compile
record exists. The run proceeds through archive creation and the final kernel
link. Adding substitutes for the bootstrap's missing symbols would address
the wrong stage.

At 10:34:19 UTC, prelink stops in `kc_image.Image.fixups()` with
`ValueError: Chained fixup imports are not supported`. This is the first
unrecovered failure. It occurs while parsing the native executable, before
prelink regression-policy checks can run.

## Binary evidence

The chained-fixup header has version 0, imports format 1, uncompressed symbol
strings, and four imports. Each import uses library ordinal -3 (weak lookup),
with its weak-import bit clear. All four also have defined section symbols:

| Import | Local definition address |
| --- | --- |
| `_iokit_physical_descriptor_close_notify` | `0xfffffff007cad054` |
| `_sheng_ethernet_probe` | `0xfffffff007cad038` |
| `_sheng_software_aes_probe` | `0xfffffff007cad040` |
| `_ml_static_mfree_prepare` | `0xfffffff007cad048` |

These are the four function substitutes introduced by the previous workflow
commit. They are weak **definitions**, rather than missing implementations.
The linker emits weak-lookup chained bindings for references to these local
definitions. XnuPrelink supports rebases here and deliberately rejects imports.
Ignoring the imports or deleting the parser rejection would leave unsupported
bindings in an image.

## Minimal change

Remove `__attribute__((weak))` from those four generated function definitions.
The workflow's selectable targets are iPadOS 27, 26 and 17; the affected
builder is the iPadOS 27 builder. Function signatures, return values and probe
behavior stay the same. The separate weak constant does not appear in this
binary's import table and is unchanged.

The fix does not change XnuPrelink or broaden its accepted input formats.

## Validation and limits

- Existing XnuPrelink host tests: 62 passed.
- Porting record checker: 17 structured areas checked.
- A targeted Apple-linker reproduction uses the actual generated support
  definitions from the fix branch, live weak-import consumers, an arm64e iOS
  target, and `-static -kernel -add_split_seg_info`. It passes on macOS 26:
  the weak variant has exactly four chained imports, and the strong variant
  has zero. The workflow YAML and its three embedded Python blocks also parse.
- Passing reproduction run: https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43010840790
- Full package and device boot results are not established by host tests.

The UniXNU checkout follows its default branch rather than the revision from
run 29, so a later package can encounter unrelated upstream changes.
The pre-existing workflow bypasses Mesa patch validation and prelink regression
checks, and reuses some outputs on file existence alone. Those behaviors remain
separate risks: a green package run would not establish source identity, ABI
compatibility or device boot correctness. They need their own evidence before
being changed. No installation seed or device secret was needed for diagnosis.
