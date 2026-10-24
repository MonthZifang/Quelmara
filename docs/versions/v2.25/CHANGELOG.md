# v2.25 — @ffi（调用外部 DLL），子集 S11

- 日期：2026-10-25
- 任务：`@ffi`（剩余 6 项里最小的一个，且对"能调 Windows API"最实用）
- 影响面：自举层（qlmc 前端 / 后端 / **导入表生成器**）/ 测试 / 文档

## 主事件：`@ffi("dll", "Sym")`

```quelmara
@ffi("user32.dll", "GetSystemMetrics")
fn metric(i: int) -> int          // 声明：没有函数体

@ffi("kernel32.dll", "Sleep")
fn sleep_ms(n: int)
```

| 环节 | 做法 |
|---|---|
| 解析 | `@ffi` 后必须紧跟 `fn` 声明；DLL 名与符号名进两张平行表，函数记录的 `nlocals` 存 @ffi 序号、`body = -1` 表示"无函数体" |
| 调用 | 声明过的函数走 `call [rip+IAT]`（新 IR 操作 `OP_CALLIAT`），槽号 = 内置 4 个之后 |
| 导入表 | **`build_rdata` 重写成数据驱动**：任意个 DLL × 任意个符号（原先两个 DLL 的偏移是手算常量）。布局 = 描述符区 → 每 DLL 一组 ILT+IAT → hint/name → DLL 名 → 字符串表 |
| 参数 | 沿用现有 ABI：前 4 个整数实参进 RCX/RDX/R8/R9，返回值 RAX（与 Win64 一致） |

## 踩到的坑：新调用形式必须进"跨调用"判定

`metric(0) + metric(1)` 第一次跑出 `2016`（stage-0 是 `3000`）：第二个参数被算成了 96。

原因：`_alloc` 里判断"临时值区间是否跨调用"时只认 `OP_CALL` / `OP_CALLRT`，**漏了新的
`OP_CALLIAT`**——于是第一个 ffi 调用的结果被当成"不跨调用"，留在 caller-saved 寄存器里，
被第二次调用清掉了。

修法：把 `OP_CALLIAT` 加进跨调用判定。**教训**：以后新增任何"会清 caller-saved 的指令"，
必须同步改 `_alloc` 的这一处（已写进坑表）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=35**（16 组用例 + 并行确定性 2 条；新增 `s12_ffi`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s12_ffi.qma` | 5 行输出与 stage-0 逐字节相同（`1920/1080/1/2/3000`） |

`s12_ffi` 调了三个真实 API：`user32!GetSystemMetrics`（屏幕宽高，确定性）、
`kernel32!GetCurrentProcessId`、`kernel32!GetTickCount`（后两个值随机，只验证"调用没崩 + 条件成立"）。
**导入表重构本身**也被全部既有用例覆盖：所有 exe 都要经加载器解析导入表才能启动。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `@ffi` 解析（`P_AT` 记号 + 声明式 `fn`）；`Fn.body = -1` 表示声明；`OP_CALLIAT` 与发射；**`build_rdata` 数据驱动重写**；`_alloc` 的跨调用判定加 `OP_CALLIAT` |
| `tests/selfhost/s12_ffi.qma` | **新增**：@ffi 差分夹具 |
| `tests/qlmc_test.py` | 用例 15 → 16 |
| `docs/05-toolchain.md` | §1.11 改 S11；坑表补「新调用形式要进跨调用判定」 |
| `docs/06-status.md` / `07-gaps.md` | 数字与 stage-1 行更新 |

## 已知边界

- 只支持**整数/指针**实参与返回（无 f64 实参、无按值结构体、无变参——`printf` 族的 `AL` 约定没做）。
- 参数上限仍是 4 个寄存器（超过要落栈，Win64 的第 5 个实参在 `[rsp+0x20]`，未做）。
- DLL/符号名写错是**加载期**错误（exe 启动即失败），不是编译期。
- 仍缺：f64、泛型、闭包、宏/反射、接口、`rc`/`Drop`；vec/map 固定容量。
