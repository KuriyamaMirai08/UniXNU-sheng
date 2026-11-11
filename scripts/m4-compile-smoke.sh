#!/usr/bin/env bash
# Public-source compilation only. Never call release/package, restore Actions
# caches, fetch device firmware, or consume a device identity/installation seed.
set -euo pipefail
test "$(uname -s)" = Darwin
test "$(uname -m)" = arm64
test "${RUNNER_NAME:-}" = UniXNU-M4
test -z "${UNIXNU_UNIQUE_CHIP_ID:-}"
device=$(cd "$(dirname "$0")/.." && pwd)
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:/opt/homebrew/opt/bison/bin:$PATH"
test -d "$DEVELOPER_DIR"
sw_vers
xcodebuild -version
test "$(xcodebuild -version)" = "$(printf 'Xcode 26.6\nBuild version 17F113')"
xcrun clang --version
xcrun --sdk iphoneos --show-sdk-version
python3 -c 'import tomllib'

# Report every missing dependency together; do not upgrade a rented machine's
# toolchain or download firmware just to find out whether it can compile.
missing=0
for formula in dtc llvm lld cmake mtools ninja glslang shaderc spirv-tools bison pkgconf rustup ipsw; do
  brew list --versions "$formula" || { echo "Missing brew formula: $formula"; missing=1; }
done
export PATH="/opt/homebrew/opt/llvm/bin:/opt/homebrew/opt/lld/bin:$PATH"
for tool in clang xcodebuild make git ninja cmake dtc fdtget fdtput aea compression_tool mformat mcopy ipsw \
            lld-link llvm-lib llvm-rc llvm-nm llvm-objcopy bison pkg-config glslangValidator glslc spirv-val rustup; do
  command -v "$tool" || { echo "Missing command: $tool"; missing=1; }
done
rustup run 1.98.0 rustc --version || { echo 'Install: rustup toolchain install 1.98.0 --profile minimal --component rust-src'; missing=1; }
test "$missing" = 0
rust_src=$(rustup run 1.98.0 rustc --print sysroot)/lib/rustlib/src/rust/library
test -d "$rust_src" || { echo 'Install: rustup component add rust-src --toolchain 1.98.0'; exit 1; }

# Fixed absolute paths: neither workspace cleaning nor temporary checkout
# removal can reach the source/BaseTools/EDK/Cargo/XNU build outputs here.
cache="$HOME/Library/Caches/UniXNU-sheng/public-smoke-v1"
mkdir -p "$cache"
export SMOKE_CACHE="$cache"
python3 - <<'PY'
import os, shutil
free = shutil.disk_usage(os.environ['SMOKE_CACHE']).free
print(f'Free space: {free / 2**30:.1f} GiB')
if free < 20 * 2**30:
    raise SystemExit('Need at least 20 GiB free; no automatic cache deletion')
PY
# Serialize across dispatch refs/workflows and fail closed after an interrupted
# process. No automatic removal of another build's lock or cached files.
mkdir "$cache/.lock" || { echo "Cache busy: inspect $cache/.lock before retrying"; exit 1; }
trap 'rmdir "$cache/.lock"' EXIT

public_checkout() {
  local url=$1 ref=$2 dest=$3
  if [ ! -d "$dest/.git" ]; then
    git -c credential.helper= clone --no-checkout --filter=blob:none "$url" "$dest"
    git -C "$dest" -c credential.helper= fetch --depth 1 origin "$ref"
    git -C "$dest" checkout --detach "$ref"
  fi
  test "$(git -C "$dest" rev-parse HEAD)" = "$ref"
  git -C "$dest" diff --exit-code --ignore-submodules=untracked HEAD --
}
mkdir -p "$cache/src"
public_checkout https://github.com/UniXNU/UniXNU.git 97437dcf7389484a0eeaa8067725ce743aff18ef "$cache/src/UniXNU"
public_checkout https://github.com/UniXNU/uefi-sheng.git 66421cb7bb5694843aec8de1ca3d1de4c20cca38 "$cache/src/uefi-sheng"
unixnu="$cache/src/UniXNU"
uefi="$cache/src/uefi-sheng"
# Only the standalone EDK package dependencies. No firmware Binaries/sheng,
# device submodule recursion, IPSW, fastboot archive, or installation runtime.
git -C "$uefi" -c credential.helper= submodule update --init --depth 1 Mu_Basecore
git -C "$uefi/Mu_Basecore" -c credential.helper= submodule update --init --depth 1 \
  MdePkg/Library/BaseFdtLib/libfdt MdePkg/Library/MipiSysTLib/mipisyst BaseTools/Source/C/BrotliCompress/brotli

export UNIXNU_EDK2="$uefi/Mu_Basecore"
export UNIXNU_BUILD_DIR="$cache/edk-package"
export JOBS=4
export CLANG_BIN
CLANG_BIN=$(python3 - "$unixnu/scripts" "$cache/toolchain" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from unixnu.util import clang_bin
print(clang_bin(Path(sys.argv[2])))
PY
)
# The pinned build.sh never cleans UNIXNU_BUILD_DIR, copies changed Conf
# templates only, and builds BaseTools only when GenFw is absent.
bash "$unixnu/package/build.sh"
for module in UniXNU UniXNUDxe UniXNURamDiskDxe HelloPayload SampleDriver XnuTest; do
  test -s "$UNIXNU_BUILD_DIR/Build/Out/AARCH64-DEBUG/$module.efi"
done

# Compile and execute a tiny offline Rust target using the project's toolchain.
# Keep source mtimes and Cargo fingerprints stable between runs.
mkdir -p "$cache/rust-probe/src"
test -f "$cache/rust-probe/Cargo.toml" || printf '[package]\nname="unixnu-m4-smoke"\nversion="0.1.0"\nedition="2021"\n' > "$cache/rust-probe/Cargo.toml"
test -f "$cache/rust-probe/src/main.rs" || printf 'fn main() { assert_eq!(std::mem::size_of::<usize>(), 8); println!("Rust ARM64 smoke passed"); }\n' > "$cache/rust-probe/src/main.rs"
export CARGO_TARGET_DIR="$cache/cargo-target"
rustup run 1.98.0 cargo run --offline --manifest-path "$cache/rust-probe/Cargo.toml"
# Real board code: host sanitizers and arm64e iOS cross-compilation, no device key.
PATH="/usr/bin:$PATH" python3 "$device/scripts/test-kcpu-allocation.py"
du -sh "$cache"
echo 'PASS: six standalone AARCH64 EFI modules, Rust 1.98.0, board helper and arm64e object. No full kernel/package/boot validation.'
