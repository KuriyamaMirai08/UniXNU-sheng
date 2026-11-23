throw 'requires separate user authorization'

# Read-only device capture checklist for Stage 0C-3 (2F).
# Never modifies partitions, GPT, slots, or Android data.
$ErrorActionPreference = 'Stop'
$outDir = Join-Path $PSScriptRoot 'captured-readonly'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# 1. Fastboot read-only state (when device is in fastbootd/bootloader)
fastboot getvar all 2>&1 | Out-File -Encoding utf8 (Join-Path $outDir 'fastboot-getvar-all.txt')

# 2. ADB read-only state (when device is booted in Android/recovery with adb authorized)
adb shell getprop | Out-File -Encoding utf8 (Join-Path $outDir 'adb-getprop.txt')
adb shell cat /proc/cmdline | Out-File -Encoding utf8 (Join-Path $outDir 'proc-cmdline.txt')
adb shell getprop ro.boot.slot_suffix | Out-File -Encoding utf8 (Join-Path $outDir 'slot-suffix.txt')
adb shell getprop ro.boot.vbmeta.digest | Out-File -Encoding utf8 (Join-Path $outDir 'vbmeta-digest.txt')

# 3. Read-only GPT header / partition table inspection (if root/block-ro available, read-only only)
# adb shell "su -c 'sgdisk --print /dev/block/sda'" | Out-File -Encoding utf8 (Join-Path $outDir 'gpt-sda.txt')
# adb shell "su -c 'sgdisk --print /dev/block/sde'" | Out-File -Encoding utf8 (Join-Path $outDir 'gpt-sde.txt')
