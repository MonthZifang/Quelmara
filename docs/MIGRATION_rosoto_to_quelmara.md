# 迁移记录：Rosoto → Quelmara

> 本文件是**唯一允许出现旧名**的地方。执行日期：2026-10-20。

## 1. 一句话

语言名从 `Rosoto` 改为 `Quelmara`；工具链内部前缀统一为 `qlm_` / `Qlm` / `QLM_`；Python 编译器整体下沉到 `tools/stage0/`（引导层），源码扩展名 `.ros` → `.qma`。

## 2. 旧名 → 新名

### 2.1 语言与产品

| 旧 | 新 |
|---|---|
| Rosoto（语言名） | Quelmara |
| `./rosoto` / `rosoto.cmd` | `./quelmara` / `quelmara.cmd` |
| `Rosoto.toml` | `Quelmara.toml` |
| `Hello, Rosoto` | `Hello, Quelmara` |
| 诊断前缀 `rosoto: …` | `quelmara: …` |
| 日志前缀 `[rosoto]` / `[rosoto-win]` / `[rosoto-a64]` | `[qlm]` / `[qlm-win]` / `[qlm-a64]` |
| `.ros` | `.qma` |

### 2.2 代码符号

| 旧 | 新 | 说明 |
|---|---|---|
| `rosoto_*`（C 函数、Python 模块名） | `qlm_*` | `rosoto_slice_bounds` → `qlm_slice_bounds` |
| `RosotoSlice` / `RosotoBuf` / `RosotoChan` / `RosotoMap` / `RosotoConn` | `QlmSlice` / `QlmBuf` / `QlmChan` / `QlmMap` / `QlmConn` | 生成的 C 里的类型名 |
| `ROSOTO_*`（宏） | `QLM_*` | `ROSOTO_URING_READY` → `QLM_URING_READY` |
| `rosoto_main`（用户 `main` 的 C 侧改名） | `qlm_main` | 避免与 C 运行库的 `main` 冲突 |

### 2.3 文件与目录

| 旧 | 新 |
|---|---|
| `tools/rosoto.py` | `tools/stage0/qlm.py` |
| `tools/rosoto_native.py` | `tools/stage0/qlm_native.py` |
| `tools/rosoto_pe.py` / `_arm64.py` / `_opt.py` / `_cli.py` / `_fmt.py` / `_dbg.py` / `_mem.py` / `_mt.py` / `_store.py` / `_uring.py` | `tools/stage0/qlm_*.py` |
| `Rosoto/rosoto/`（仓库目录） | `Quelmara/quelmara/` |
| GitHub `MonthZifang/Rosoto` | GitHub `MonthZifang/Quelmara` |

## 3. 替换规则（可复现）

迁移用 `tools/dev/migrate_names.py` 一次性完成，规则**有序、大小写敏感、幂等**：

| # | 正则 | 替换 |
|---|---|---|
| 1 | `(?:Rosoto\|rosoto)\.toml` | `Quelmara.toml` |
| 2 | `ROSOTO_(?=[A-Za-z0-9_])` | `QLM_` |
| 3 | `\bROSOTO\b` | `QLM` |
| 4 | `Rosoto(?=[A-Z])` | `Qlm` |
| 5 | `Rosoto` | `Quelmara` |
| 6a/6b | `from rosoto` / `import rosoto` | `from qlm` / `import qlm` |
| 6 | `rosoto_` | `qlm_` |
| 7 | `\brosoto\.py\b` | `qlm.py` |
| 8 | `\[rosoto` | `[qlm` |
| 9 | `\brosoto\b` | `quelmara` |
| 10/11 | `tools/qlm_` / `tools/qlm.py` | `tools/stage0/…` |

顺序很关键：`rosoto_*`（规则 6）必须早于 `\brosoto\b`（规则 9），否则 `rosoto_native` 会先被规则 9 拆成 `quelmara_native`；`Rosoto*` 类型（规则 4）必须早于语言名（规则 5）。

## 4. 破坏性变更清单

1. **`.ros` 不再被接受**：编译器直接报错并给出 `git mv` 命令。
2. **`Rosoto.toml` 不再被读取**：检测到遗留文件时报错提示改名（不静默退回默认配置）。
3. **生成的 C 代码符号变了**：若有人手写了依赖 `rosoto_*` 的 C 代码，需要跟着改。
4. **`str` 的 `<` / `>` 语义**：文档曾写"字典序"，实际是**指针比较**（bug）。本次改名不改语义，已标记为待修项（见 `HANDOVER.md`）。
5. **`[rosoto]` 日志前缀变成 `[qlm]`**：依赖日志解析的外部脚本需要同步。

## 5. 迁移命令（如需重跑）

```bash
git tag pre-quelmara-rename
python tools/dev/migrate_names.py --dry --scope code   # 先看命中
python tools/dev/migrate_names.py --scope code
python tools/dev/migrate_names.py --scope docs
```

## 6. 验证

```bash
python tools/dev/check_names.py                 # 旧名残留 / .ros 残留 / C 运行时自洽
python tests/run_win_tests.py                   # Windows PE 74 项
./quelmara version
```
