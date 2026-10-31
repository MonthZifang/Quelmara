# v3.48 — `file_size` / `read_text` 落地；覆盖率 48 → 49

- 日期：2026-10-31
- 任务：用户要求"继续"；解决 v3.46 遗留的 `file_size`（§7.37）
- 影响面：`bootstrap/qlmc/qlmc.qma`（2 个 kernel32 IAT 槽 + 2 个内建）、
  `tests/t191_qlmc_fileio.qma`、`tests/run_win_tests.py`
- 覆盖率：**48 → 49**（`std/staticfile` 通过）
- 回归：PASS=364 → **365** FAIL=0 SKIP=0

## 真根因：`I_CREATE` 其实是 `CreateThread`

v3.46 把 `file_size` 失败归因于「`_emit_call_args` 对同一 vreg 出现在多个
实参位置处理不一致」（登记在 §7.37）。**那个归因是错的。**

这版用 `irdump` 对照 `@ffi` 7 参（已知可用）与内建 7 参的 IR，发现两者
形状**完全一致**（都是 3 个独立零值 + `STKALLOC 64` + `STKARG 32/40/48`）。

于是加了一条临时诊断打印 `CreateFileA` 的返回值：

```
0          ← CreateFileA 返回 0，不是 -1 也不是有效句柄
```

`CreateFileA` 失败应当返回 `INVALID_HANDLE_VALUE (-1)`，返回 **0** 说明
**调用根本没到达 `CreateFileA`**。

查 IAT 才发现：`I_CREATE = 4` 指向 `iatb.get(0) + 24` = kernel32 `slot[3]`，
而 dump 出来的 `slot[3]` 是 **`CreateThread`**。`I_CREATE` 是历史命名，
它一直是 `CreateThread`（`spawn` 用的），**`CreateFileA` 从来不在内置
导入表里**。

所以 v3.46 的 `file_size` 是在调 `CreateThread(path, GENERIC_READ, ...)`
—— 参数全错，返回 0 完全合理。

## 修复

新增 `I_CREATEFILE = 16`（真正的 `CreateFileA`）和 `I_READFILE = 17`，
ws2_32 后移到 18..29，`I_USER` 30。

`I_CREATE` 保留原名不动（改名会牵动 `spawn`），但在 `I_CREATEFILE` 旁边
写了注释警告：

```quelmara
// v3.48：CreateFileA。**注意 `I_CREATE`(4) 其实是 CreateThread**（历史
// 命名，spawn 用的），不要拿它调 CreateFileA —— v3.46 就是这么错的，
// 结果 file_size 恒返回 0xFFFFFFFF。
const I_CREATEFILE = 16
```

## 两个内建

| 内建 | 实现 |
|---|---|
| `file_size(path)` | `CreateFileA` → `GetFileSize` → `CloseHandle`；打不开返回 -1 |
| `read_text(path)` | 同上 + `alloc(size+9)` + `ReadFile` + 写长度头 + 末尾 NUL；失败 fail-fast |

`read_text` 的失败语义与 `file_size` 不同，这是**故意的**：

* `file_size` 打不开返回 **-1**（"文件不存在"是可恢复结果，
  `std/staticfile` 靠它给 404）；
* `read_text` 打不开 **fail-fast**（退出码 9；读不到文件是调用方的 bug）。

`GetFileSize` 的第 2 参给真实 8 字节缓冲而不是 `NULL` —— 它要往里写高位，
传 `NULL` 在某些实现上会崩。

## 验证

```
file_size=2486
read_text len=2486
match=1
```

`README.md` 的真实大小是 2486 字节（与 PowerShell `Get-Item` 一致），
`read_text` 读出的长度与之相等。

`tests/t191_qlmc_fileio.qma` 四项断言：已知文件大小为正是、`read_text`
长度与 `file_size` 一致、首字节是 ASCII、缺失文件返回 -1。

## 关于 §7.37

那条登记把根因写错了。现在改成了「`I_CREATE` 名字误导」——
**这是本项目第二次因为"变量名/常量名与实际语义不符"而浪费一整版**
（上一次是 v3.45 的 `_op_name` 表错位）。

教训写进 §7.37：**怀疑 IR 生成之前，先核对调用的 IAT 槽到底指向哪个符号**。
`irdump` 只显示 `CALLIAT imm=N`，不显示 N 对应哪个 API —— 这是个工具缺口。

## 回归与自举

```
PASS=365 FAIL=0 SKIP=0
自举五级链：stage-2 可用且与 stage-1 逐字节等价（30/30 组，不动点成立）
```
