# UniXNU-sheng 设备测试审批包清单（Stage 0C-3）

**当前状态：设备 NO-GO。** 首次只读实验与首次写入实验必须分开审批。

## 一、已离线 / CI 证明项
- **2F 归档与 A-only 恢复**：
  - `outputs/stage0c3/2f/gpt-attributes-decoded.json`：16 个 A/B 分区历史/原厂 GPT 属性解码（`boot_a` `0x77` 为 active/successful）。
  - `outputs/stage0c3/2f/make-a-only-restore.py` + `test_make_a_only_restore.py`：仅允许 AVB 绑定的 6 个 `_a` 分区，拒绝 `_b`/`_ab`/`userdata`/`persist`/`modem`/`gpt`/`--set-active`/`erase`/`-w`。
  - `outputs/stage0c3/2f/device-readonly-capture.ps1`：只读取证清单（带人工授权阻断）。
- **2B 生产输入与同构建绑定（Run S `45101784411` + Run P `45105676166`）**：
  - 48 GiB APFS seed：`9c7d8c86fb56aa6dd2d9a65b0345a8b580a4cb0b391e9b8265db0197b9fcffea`（`1,183,872` B，container `f64b5730fc854831905eae28cbc348f7`，volume `95DAF626-3877-4A1E-BABD-86AA7A445D0A`），approval SHA `528d882db0b79589e3ca50bae276ecb3fd71a320755484733bd0b6e111f120c8`。
  - Run P 同次构建绑定：raw `5d73cb56...`、sealed `a186a16f...`、FAT `ecd742dc...`、vroot `e0787c6c...`、DarwinBoot `ACCEPT`、PlaceImage `99,876,864` B（75,472,160 B FAT 余量）。
- **2C 早期执行与物理权限**：
  - `2c-rebase-pac-ownership.json`：242,519 处 fixup 与 267 处 load-command 头均在 bootstrap RW/NX 段，0 处写 RX。
  - `2c-static-if-callback-closure.json`：2 个回调入口、2 个可达函数、0 间接跳转、0 非 RX 页。
  - `2c-efi-excluded-ranges.json`：`darwinboot_memory_size = 5100273664`。
- **2D/2E 存储隔离与账本**：
  - `outputs/stage0c3/2d/ledger_proto.py` + `test_ledger_proto.py`：LBA `51119339..51119354`（16 块），8 个写边界断电注入及负例全过；`stage0c3-ledger.patch` 通过 `run-stage0c2e-host.py`（624/624）、C++ `UfsWriteRole::Ledger` 单测与 `aarch64-none-elf` 探针。

## 二、仍须真机单独授权观测项（未证）
1. **2F 当前平板实机状态**：运行 `device-readonly-capture.ps1` 取得当前双 GPT、活动槽/成功计数、boot LUN、ABL/UEFI 版本、AVB 回滚索引与可用原始备份。
2. **2B/2C 目标装载与寄存器**：真实 `ExitBootServices` 后的最终 EFI 内存图与排除区、目标侧 `TTBR0/1`、`TCR`、`SCTLR/WXN/BTI`、缓存/TLB 生效与指令一致性。
3. **2D/2E 真实介质与控制器**：真实 UFS 介质所有权、完整窗口旧格式检查、DMA 撤权/控制器复位/断电续接。首次只读试启（无持久写）与首次持久写必须分两次独立审批。
