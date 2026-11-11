#!/usr/bin/env bash
set -euo pipefail
test "${RUNNER_NAME:-}" = UniXNU-M4
test "$(uname -m)" = arm64
test -z "${UNIXNU_UNIQUE_CHIP_ID:-}"
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:/opt/homebrew/opt/bison/bin:$PATH"
export HOMEBREW_NO_AUTO_UPDATE=1
for candidate in /opt/homebrew/bin/python3 /opt/homebrew/opt/python@3.*/libexec/bin/python3; do
  if [ -x "$candidate" ] && "$candidate" -c 'import tomllib' 2>/dev/null; then
    export PATH="$(dirname "$candidate"):$PATH"
    break
  fi
done
python3 -c 'import tomllib'
for formula in unifdef cmake ninja bison; do
  brew list --versions "$formula" || brew install "$formula"
done
test "$(xcodebuild -version)" = "$(printf 'Xcode 26.6\nBuild version 17F113')"
mkdir -p "$M4_LOG_DIR"
exec > >(tee -a "$M4_LOG_DIR/console.log") 2>&1
export PYTHONUNBUFFERED=1 ZERO_AR_DATE=1 JOBS=4
# A copied Xcode can answer -version and xcrun yet fail real xcodebuild
# targets because its system CoreSimulator framework was never installed.
# Initialize only when required, never ask for/handle an administrator password.
if [ ! -d /Library/Developer/PrivateFrameworks/CoreSimulator.framework ] || ! xcodebuild -checkFirstLaunchStatus; then
  echo 'Xcode system components are incomplete; running the official first-launch initializer'
  if sudo -n true 2>/dev/null; then
    sudo -n env DEVELOPER_DIR="$DEVELOPER_DIR" /usr/bin/xcodebuild -runFirstLaunch
  else
    /usr/bin/xcodebuild -runFirstLaunch </dev/null || {
      echo 'Administrator setup is required on the Mac: sudo env DEVELOPER_DIR=/Applications/Xcode_26.6.app/Contents/Developer xcodebuild -runFirstLaunch'
      exit 1
    }
  fi
fi
python3 - <<'PY'
import os, shutil
free = shutil.disk_usage(os.environ['M4_ROOT']).free
print(f'Persistent XNU root: {os.environ["M4_ROOT"]}; free: {free / 2**30:.1f} GiB')
if free < 35 * 2**30:
    raise SystemExit('Need 35 GiB free; no cache files were removed')
PY
mkdir "$M4_ROOT/.lock" || { echo 'Persistent build busy; inspect lock before retrying'; exit 1; }
trap 'rmdir "$M4_ROOT/.lock"' EXIT
unixnu="$M4_ROOT/UniXNU"
if [ ! -d "$unixnu/.git" ]; then
  git -c credential.helper= clone --no-checkout --filter=blob:none https://github.com/UniXNU/UniXNU.git "$unixnu"
  git -C "$unixnu" -c credential.helper= fetch --depth 1 origin 97437dcf7389484a0eeaa8067725ce743aff18ef
  git -C "$unixnu" checkout --detach FETCH_HEAD
fi
test "$(git -C "$unixnu" rev-parse HEAD)" = 97437dcf7389484a0eeaa8067725ce743aff18ef
# Disable credential helpers for public source fetches; no token is supplied.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=
python3 "$M4_ROOT/device/scripts/m4-xnu-corecrypto.py" --unixnu "$unixnu" --out "$M4_ROOT/out" --logs "$M4_LOG_DIR"
