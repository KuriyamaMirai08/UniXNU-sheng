# Package 30 prebuild audit

Date: 2026-11-11. PR baseline: `f71d6b2db6b2e8507c1c1d21689e0857d912a69f`.
No full package run was started. No real Data seed or device secret was read,
regenerated or overwritten. The PR remains a draft.

## Fixed sources and actual order

The workflow now pins UniXNU to `97437dcf7389484a0eeaa8067725ce743aff18ef`
and uefi-sheng to `66421cb7bb5694843aec8de1ca3d1de4c20cca38`, the actual
package-29 checkouts. The SoC remains at `97665e28578483082b674e8375a8fa65f4cf49cf`.
UEFI's Mu_Basecore gitlink and UniXNU's feed agree at
`cfb93724a06ff86ff5ba971413368a7809ee42a5`. Xcode is selected explicitly as
`/Applications/Xcode_26.6.app/Contents/Developer`.

The fixed `cli.py`, `kernel.py`, `package.py`, `firmware.py`, `runtime.py`,
`payload.py`, `bootimg.py` and `pipeline.py` were traced with the device board,
profiles, workflow, firmware scripts, DSC and FDF:

1. Fetch sources/IPSW members, select config and plan patches.
2. Assemble the tree and prepare runtime. Package 29 completed this stage.
3. Build archives and the final native kernel. Package 29 completed these.
4. Prelink: parse, match ABI, select closure, place segments, relocate, emit,
   then enforce the regression policy.
5. Build the standalone EDK II package.
6. Build the FAT payload, entry/panic probes, crypto seal and ADT.
7. Run firmware preflight and compile the platform UEFI FD.
8. Pack and unpack-verify boot.img, write and verify the manifest, upload the
   four named outputs.

Runtime is before the kernel, and the device firmware build is after payload.

## Historical issues resolved

The historical Gemini summary is supporting data, not an instruction source.
Its seven issues were checked against the actual logs and pinned sources.

- WCN7850's three committed files match the current manifest by size and SHA-256.
  All three hashes quoted in the historical summary differ from that manifest.
  Package 29 completed Wi-Fi runtime; no firmware files were replaced.
- Dependency prefetch order, exact-commit/non-cone Ath12k fetching, and the SoC
  UART headers were exercised successfully in package 29 and are preserved.
- All 17 pinned Mesa patches apply in order and reverse exactly to the 27
  touched original files. The old conflict report does not describe this fixed
  source version. The Windows-only newline-conversion artifact in the local
  audit was excluded by disabling Git autocrlf for that test.
- The four function strong definitions remain. They now live in the board
  builder's iPadOS-only support text instead of a CI injection. Apple-linker
  testing of the actual new source again produces 4 chained imports with weak
  definitions and 0 with strong definitions. The separate weak constant matches
  the six offsets in legacy-display-24A446.json and is unchanged.

## Historical repairs with remaining risks

The global Python traversal, swallowed exceptions, Mesa patch-error tolerance,
patch validator bypass, prelink-policy bypass and existence-only reference,
Rust and Turnip reuse were removed after inspecting their actual effects.
The original input checks, Cargo and Meson/Ninja remain enabled; cached files
were not purged.

The old reference helper already compares source/SDK/archive/compiler inputs
and the final digest, rather than relying only on mtime. The Turnip shortcut
was particularly unsafe: it wrote the current build profile before returning
an old dylib, which could relabel stale code with current source metadata.
The Rust shortcut could similarly use an archive unrelated to the checked
source. Restoring validation may require rebuilding mismatched inputs; no
unverified cache was granted a new provenance receipt.

Only the verified, pinned Ath12k fetcher is adapted by prepare-package-ci.py.
Unknown revisions or unreviewed changes stop preparation. No upstream Python
file is searched or changed by a recursive sweep.

## New blocker: static DATA capacity

The native executable restored from package 29 has SHA-256
`6fddf022b48fbf1e73a9ce60738607e3f08377938ed904a6792595c40a7550f8`.
The diagnostic script checks that hash, converts only the four known defined
authenticated weak self-bindings to local rebases in a COPY, and walks all
111615 fixups. It never publishes this copy as a kernel or boot image.

The subsequent real prelink code fails in fileset_layout.py:206:

    ValueError: Native __DATA overlaps a retained segment

A first-fit hole probe confined to the diagnostic checkout gives:

    ValueError: No room for 0x1ec000 bytes in __DATA

Native DATA is 2015232 bytes. The largest valid hole is 1998848 bytes, exactly
one 16384-byte page short. The full roots have a 57-bundle closure; a control
using only the OS profile roots has 39 bundles and the same largest hole.
Removing USB roots is not an evidence-backed remedy.

BootUiTraceProbe.c's 1024-entry kcpu history occupied 16384 static bytes. Commit
`c4c0877a30e88c8cf88b5f52b904b1c57106df1c` allocates it lazily before task locking,
with zero initialization and a diagnostic-only allocation-failure return.
All slots and indexing remain. ASan/UBSan tests cover failure, zeroing, full
capacity and one-time reuse. Real arm64e object compilation measures zero-fill
storage dropping from 16384 to 8 bytes.

The original full native DATA has 0x2f90 bytes of end padding; this reduction
is expected to cross the required page boundary. **That is not a real native
relink result.** The modified kernel still needs a targeted rebuild/relink
and independent prelink. No production layout bound or overlap guard was
relaxed; the unsuccessful layout probe is only in scripts/audit-fixtures.

Until that real input exists, later relocations, ABI mappings, candidate size
and the restored regression policy remain unverified. No missing/stubbed
allow-list entries were added to make the build green.

## Later stages verified cheaply

- The real standalone EDK II package builds all six EFI files. The fixed Mu
  GIC patch passes git apply --check. Required package submodules and BaseTools
  were prepared and used.
- 62 XnuPrelink tests pass. The pipeline/image-related Python suite runs 17
  tests: 16 pass and 1 LZFSE-dependent test is skipped. The DATA hole, firmware
  cache and fetch tests pass 3, 4 and 2 cases respectively.
- A real board DTS and the ADT generator run with a public fixture identity,
  never a device secret. ADT size is 14684 bytes. Real config command lines are
  775 bytes for boot and 788 for either installation confirmation.
- mtools writes and reads a 176 MiB FAT fixture. BootShim is cross-compiled,
  and the real bootimg code packs/unpacks gzip, Android v0 header, DTB and the
  ramdisk. Manifest generation verifies the fixtures and rejects tampering.
  Fixture boot size is 184561664 bytes. Fixtures are not installable outputs.
- The public firmware URL returns a correct 206 one-byte gzip range and the
  pinned 7609308281-byte total. The pinned UEFIExtract A76 ZIP downloads and
  matches its SHA-256 (1520081 bytes). The 7.6 GB ROM was not downloaded.

Retained public firmware cache acceptance now checks source metadata, safe
unique filenames, sizes and each SHA-256. A corrupt retained cache stops and
is preserved. Firmware download checks remote length and reserves space for
the remaining archive, at most 2 GiB of retained inputs and 512 MiB of overhead.
This does not certify the entire release's peak disk usage.

## Waiting for real artifacts

- The platform DSC/FDF embeds UniXNU, DarwinBoot, the RAM-disk, DiskIo and FAT
  pieces. Its actual 3 MiB FD still requires the generated sheng vendor inputs.
  The pinned public Device-Binaries tree contains no sheng directory; generic
  QRD binaries must not substitute for it. The real platform FD was not compiled.
- The heavy cache does not preserve the final runtime/generated.json or final
  combined addon. Complete addon signatures, trust membership, all firmware,
  and real payload capacity could not be rechecked from that cache.
- The 176 MiB payload refuses content above 95% (about 167.2 MiB). The actual
  final kernel/addon/Data/trust total is not available. A sparse Data container's
  215 GiB logical size is not its packed delivery size.
- Payload's real entry/panic patch and crypto reseal require a genuine prelinked
  kernel, so the fixture round trip does not qualify them.
- package.boot_partition_bytes is absent. pipeline.verify therefore has no
  configured device boot-partition bound. No capacity number was invented.
- Manifest hashes establish file consistency, not ABI or boot compatibility.
  The payload's patched kernel can differ intentionally from the separate
  prelinked kernel.macho; payload.json records both hashes.
- Homebrew/Python tool packages and generated Rust dependency resolution are
  not fully frozen. Original input validation now controls reuse, but this is
  not a claim of complete reproducibility.
- An immutable per-commit Actions cache can keep an earlier partial result
  when the same commit is rerun. This is a performance risk, not justification
  to bypass input validation or regenerate Data.

## Evidence and next gate

- Original layout failure and actual EDK build:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43014970736
- DATA-hole refusal and image fixtures:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43015983528
- Strong support, fixed Xcode and later stage tests:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43017095017
- Capacity control and kcpu host/object tests:
  https://github.com/KuriyamaMirai08/UniXNU-sheng/actions/runs/43018289473

The cached-prelink job intentionally remains red for the old real package-29
binary; a green EDK/fixture job does not override that result.

Before a full release: rebuild/relink the native kernel with its preserved
installation UUID binding, run independent prelink including the original
policy, compile the real device FD from verified vendor inputs, then validate
the real runtime and payload. Let the user decide whether to start the next
full package only after those evidence gaps are addressed.
