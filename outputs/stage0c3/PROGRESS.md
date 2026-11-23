# UniXNU-sheng Stage 0C-3 进度记录

## Step 0: 环境与离线基线复验
- Git 环境：使用 PortableGit 2.55.0.windows.3 + `gh auth setup-git`；在 `stage0c1f-ci-work` 添加 `fork` 远端 (`https://github.com/KuriyamaMirai08/UniXNU-sheng.git`)，分出 `stage0c3-seed` (`codex/stage0c3-seed`) 和 `stage0c3-production` (`codex/stage0c3-production`)，均基于 `975edf57b1b93a0310ee234177ff04081e515095`。
- 离线五项复验（输出至临时目录 `C:\Users\13463\AppData\Local\Temp\97e651a3-dcc9-4166-ae17-32ef7e9ced11`）全部通过：
  1. `verify-stage0c2c-preimage.py`: 49 fileset 成员，131/492 页，5 parser 反例，封印 10 处，HMAC MATCH，FAT `production=false`，`darwinboot=ACCEPT`，`device=NO-GO`。
  2. `audit-stage0c2b-fat-followup.py`: PlaceImage 98,697,216 B，根策略两正六反，48/64 GiB 均在预算内。
  3. `test-stage0c2c-bootstrap-retag.py`: 2C 几何与 7 项格式拒绝通过，每别名 48 L2 块，38/39 位边界通过。
  4. `test-stage0c2d-ownership.py`: 38 用例通过，`PASS_SYNTHETIC` / `install_allowed=false`。
  5. `audit-stage0c2b-repro.py`: `2D->2B` 链接前差异对照通过。

## Step 1: 2F 离线工作
- 已解码 16 个 A/B 分区历史与原厂 GPT 属性位域 (`outputs/stage0c3/2f/gpt-attributes-decoded.json`)：按 Qualcomm 槽位权威 `boot_a`/`boot_b` 自动生成摘要，历史 `boot_a` (0x77) 为 `active=True, successful=True, unbootable=False, priority=3, retry=6`，`boot_b` (0x2a) 为 `active=False, successful=False, unbootable=False, priority=2, retry=5`；其余分区高字节另行枚举。
- 已生成 A-only 恢复脚本生成器 (`outputs/stage0c3/2f/make-a-only-restore.py`) 及负例回归测试 (`outputs/stage0c3/2f/test_make_a_only_restore.py`)：仅允许经 AVB 描述符绑定且处于白名单内的 6 个 `_a` 分区，拒绝 `_b`、`_ab`、`userdata`、`persist`、`modem`/`fsg`/`efs`、`gpt`、`--set-active`、`erase`、`-w` 及哈希篡改，测试全部通过。
- 已生成只读取证清单脚本 (`outputs/stage0c3/2f/device-readonly-capture.ps1`)，顶部强制 `throw 'requires separate user authorization'`，本轮未运行。
- 明确结论：原厂 `flash_all_except_storage.*` 脚本操作配对的 `_ab` 目标（见 `2f-stock-recovery-script-operations.json`），**不能用于仅恢复 A**。

## Step 3 (部分): 2D/2E 持久账本与 2C 补充审计脚本
- 账本位置与原型：`outputs/stage0c3/2d/ledger_proto.py` 与 `test_ledger_proto.py` 全部通过（`PASS_SYNTHETIC`，`trusted_media_observation=NOT_OBSERVED`，`install_allowed=false`）。账本置于 `[window_first - 1024 - 16, window_first - 1024)`（48 GiB 规划下为 LBA `51119339..51119354`），严格位于 root 镜像区结束（`40495616`）之后、1024 块守卫区之前，不改 `PersistWalV2.h` 与 W 公式。覆盖 8 个写边界断电注入、重放、错盘、split-brain 及重叠拒绝。
- 驱动补丁：`scripts/repro/stage0c2e/stage0c3-ledger.patch` 新增 `UfsWriteRole::Ledger = 5` 与只读 `native_ufs_ledger_open` / `native_ufs_ledger_read`，`git apply --check` 及 Windhawk `clang++` `--target=aarch64-none-elf` freestanding 探针通过。
- 2C 补充审计脚本：`scripts/repro/stage0c2e/audit-stage0c3-2c.py` 已就绪（rebase/PAC RW-RX 归属、`llvm-objdump` `static_if` 回调闭包、EFI 排除区间），待随 Run P 执行。
- 补丁与主机回归修复：`stage0c3-ledger.patch` 移除不存在的 `gStoreGeometry.protectedFloor` 引用；在临时副本叠加 `stage0c2d-shengufs-resume.patch` + `stage0c3-ledger.patch` 后，`run-stage0c2e-host.py`（624/624 WAL + UFS/RamBlock/BootLog）全部通过，新增 C++ 单元测试 `UfsWriteRole::Ledger` 注册与重叠拒绝通过，Windhawk `aarch64-none-elf` freestanding 探针（含 `UfsWriteAuthority.h` 与 `native_ufs_ledger_open`/`native_ufs_ledger_read`）编译通过。
- 2C 审计脚本加固：`audit-stage0c3-2c.py` 修正引导期非可执行段（含 `__DATA_CONST`、`__TEXT` 等在 `arm_vm_prot_finalize` 前由 `start.s` 映射为 RW/NX 的区间）归属判定与 `objdump` 自动定位，并统计间接跳转数；在 Run 41 历史 `kernel.macho` 上离线冒烟验证通过（`bootstrap_rw_owned=242504, rx_violation=0, unmapped=0`）。

## Step 2: 2B-a Run S 生产 48 GiB APFS Seed 生成与离线准入
- Run S (`45101784411`, `codex/stage0c3-seed@f13646965fc736cb1b5138719c1f3e2bfdf6f3ec`, runner `20261117.0516.1` / `25G332`) 成功。
- 本地解密与校验通过，明文保存在 `ROOT\_private-inputs\seed-20261123\data.dbr`（另留加密备份 `data.dbr.enc.bak`）：
  - `packed_sha256`: `9c7d8c86fb56aa6dd2d9a65b0345a8b580a4cb0b391e9b8265db0197b9fcffea` (`1,183,872` B)
  - `logical_bytes`: `51539607552` (48 GiB)
  - `apfs_container_id`: `f64b5730fc854831905eae28cbc348f7`
  - `volume_uuid`: `95DAF626-3877-4A1E-BABD-86AA7A445D0A`
  - `nonfree_main_bytes`: `116715520`
  - `approval_sha256` (`seed-approval.json`): `528d882db0b79589e3ca50bae276ecb3fd71a320755484733bd0b6e111f120c8`
- 离线准入 `check-stage0c2d-production-seed.py` 输出 `PASS offline APFS seed binding`（`static_seed_admission=PASS`, `initialization_allowed=false`, `live_media_ownership=NOT_OBSERVED`, `device=NO-GO`）。

## Step 4 & Step 5: 2B-b Run P 生产绑定 CI、归档复核与收尾
- Run P (`45105676166`, `codex/stage0c3-production@78afa4ea949a2e841b055abc96e2638553d2d9ee`) 成功，21 份脱敏 JSON 已归档至 `outputs/stage0c3/run-45105676166/` 并重算 `sha256.txt`：
  - raw kernel: `5d73cb56e7c24891edc781a8a4776b3dd04ab9e641f5dbf8984dc1dbf024e16b` (`98,648,064` B)
  - sealed kernel: `a186a16f5f8bbb24ac4bf8541dc5b5fb7c7ad87c63b48c63814dea8f74eb3628` (`98,648,064` B)
  - FAT: `ecd742dc52544982f148eb9d967ab5e9952d1352724e9c6bdf17ec5d6e4484bc` (`184,549,376` B)，回读 `scratch-data.img` 与生产 seed `9c7d8c86...` (`1,183,872` B) 一致，`darwinboot=ACCEPT`，`production_inputs=true`，`loadable=false`，`runtime_qualified=false`，`device=NO-GO`。
  - 2C 三项审计全部 `PASS`：rebase/PAC `242,519` fixups + `267` headers 均在 bootstrap RW，`0` RX 违规；`static_if` 回调闭包 `2` 入口、`2` 可达函数、`0` 非 RX 页；EFI 窗口 `5,100,273,664` B。
- 本地 `PlaceImage` 与根策略复核 (`outputs/stage0c3/run-45105676166/followup-placement-root.json`) 通过：`used_bytes=99,876,864`，95% FAT 余量 `75,472,160` B，48 GiB 窗口 `W=12,624,640` 块（LBA `51,120,379–63,745,018`），账本 LBA `51,119,339–51,119,354`。
- 已更新 `porting.toml` 并生成 `outputs/stage0c3/DEVICE-APPROVAL-CHECKLIST.md`，设备维持 `NO-GO`。

## 2F 真机只读取证（ADB + root，未进 Fastboot）
- 实机状态已归档至 `outputs/stage0c3/2f/live-readonly-audit.json`（原始二进制及设备标识仅留仓外 `_private-inputs/device-2f-20261123/`），设备未做任何写操作，保持 `NO-GO`：
  - 系统：`OS3.0.306.0.WNXCNXM`（官改，`init_boot_a` 与 `init_boot_b` 哈希不同，`vbmeta` `flags=3`）；`vbmeta_system` `rollback_index=1769904000`（与归档 `303` 一致）。
  - 分区：`sda`–`sdf` 全部 6 个 LUN 主/备 GPT 头与分区表 CRC 全部通过且完全一致；全部 16 个 A/B 分区范围与原厂一致；`userdata` 为 `sda29`（LBA `3094592..64007162`，`249,497,890,816` B，FBE 加密 `f2fs`），尚无 `darwin` 分区。
  - 槽位：`boot_a` `0x0077000000000000`（`active=True, successful=True`），`boot_b` `0x003b000000000000`（`active=False, successful=False`）。
