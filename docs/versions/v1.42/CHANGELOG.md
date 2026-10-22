# v1.42 — 函数值放宽：callr 8 参 + 聚合/切片实参（语言层黄标翻绿）

- 日期：2026-10-23
- 任务：语言层 §1 函数值 🟡 → ✅：`callr` 参数上限 6 → 8（x86-64 走栈传参，
  实际不设上限），实参放开 struct/slice（按值编组）。
- 影响面：自研 ABI（x86-64 栈传参 + A64 参数寄存器扩到 8）、callr 编组、
  测试（t87）、文档

## 为什么是它

P1-4 明文项。旧限制的根：`call`/`callr`/`args` 三处都把全部实参塞进 6 个
参数寄存器（ARG_REGS[i] 直接索引，>6 直接 IndexError），且**自研 ABI 没有
栈传参**——所以 8 参不是"把检查改成 8"就完事，要先给 ABI 补溢出区。
聚合实参则简单：直接调用已有"拷临时帧槽传地址"的编组（v1.2 起），callr
照搬即可。v1.37/v1.39/v1.41 铺好的"多字槽 + 按值拷贝"机制再次复用。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | **ABI 栈传参**：`_emit_call_args`（前 6 参走既有并行搬移，第 7 参起 `sub rsp` 开溢出区、逐参经 SCRATCH 存 `[rsp+8j]`，call 后回卷）；`args` 指令第 7+ 形参从 `("stk", j)` 源读（`_stkarg_base` 算偏移）；`emit_move` 加 `("stk", j)` 形态 |
| `tools/stage0/qlm_native.py` | callr 编组：删 6 参上限与聚合拒绝；slice 实参拷 2 字头、struct/enum 实参按 agg_size 拷进临时槽传地址（与直接调用同语义） |
| `tools/stage0/qlm_arm64.py` | `ARG_REGS` 扩到 X0-X7（SysV AArch64 本就 8 个，X6/X7 此前闲置）；call/args/callr >8 实参 fail-fast（栈传参未接） |
| `tests/t87_callrelax.qma` | **新增**：6 组覆盖（8 参直接/间接调用、同变量分派两种 8 参目标、struct 实参 + 值语义、切片实参、既有小参数量路径不回退） |
| `tests/run_win_tests.py` | 注册 t87（主回归 149 → 150） |
| `tools/stage0/qlm_cli.py` | VERSION 1.41.0 → **1.42.0** |
| `docs/02-language.md` | 类型表/§函数值 边界更新（返回值按标量、无签名校验的信任级） |
| `docs/07-gaps.md` | §1 函数值 🟡→✅（无捕获归"闭包"红标行）；§8 推进顺序同步 |
| `docs/06-status.md` | 回归 150 / lexdiff 135 / parsediff 119 / irdiff **PASS 67**（t87 的 8 参 A64 走 X6/X7）/ bodydiff 一致 1202 |

## 实现要点

- **栈传参布局**：调用点 `sub rsp, 8k` → 第 7+j 参存 `[rsp+8j]` → `call` →
  `add rsp, 8k` 回卷。被调方从 `[rbp + 8*(2+n) + 8j]` 读——**不是** `[rbp+16]`：
  序言在 push rbp 之前先压 callee-saved（首轮探针踩过：直接调用"通过"是
  保存的 r13 恰好等于期望值的运气，公式修正后两个探针 + t87 才真稳）。
  偏移由被调方自己的 `used_callee`（及线程入口的两次额外 push）决定，
  双方都是本编译器生成，自洽。
- **发射层顺序安全性**：参数搬移只写 ARG_REGS 与 SCRATCH（都在分配池外），
  池寄存器与 RBP 相对槽不受影响——栈实参取值在搬移前后读都正确；
  栈实参的物化用 SCRATCH，与 r10（callr 目标寄存器）互不干扰。
- **≤6 参调用机器码逐字节不变**：`_emit_call_args` 对 6 参以内走与旧代码
  完全相同的 `parallel_move + call` 序列——这是"无回退"的结构性保证，
  bench 实测印证。
- **A64 不对称边界**：x86-64 栈传参不设上限；A64 用满 8 个寄存器、>8
  编译期明确报错（irdiff SKIP 纪律同 map/trunc）。t87 恰好 8 参，
  在 A64 上直接通过（irdiff PASS 66→67）。
- **语义边界（如实登记）**：间接调用无签名信息——返回值按标量处理
  （聚合/切片返回的函数不可间接调用）；聚合实参要求目标形参是聚合类型，
  与标量路径"实参原样传"同信任级；仍无捕获（闭包是独立红标行）。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=150 FAIL=0 SKIP=1**（v1.41 为 149；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t87_callrelax.qma --target win` | ok（6 组全过） |
| `python tools/stage0/qlm_cli.py run tests/t38_callr.qma --target win` | ok（既有 callr 回归不回退） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 135 / 119 全绿 |
| `python tests/bodydiff.py` | 一致 1202 / 分叉 872 / SKIP 24-18（无新增 MISMATCH） |
| `python tests/irdiff.py` / `emitdiff.py` | **67**-0-48 / 10-0（irdiff PASS +1：t87 A64 通过） |
| 性能（改动前 = git worktree@HEAD(v1.41) 基线） | 见下——**无回退** |

性能对照（基线 → 改动后；VBS 噪声带 ±50%）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 41 / 9 / 77 / 2 ms | 42 / 9 / 80 / 3 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.84 / 48.0 / 4.17 / 39.8 ms | 3.97 / 48.2 / 4.15 / 40.0 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.75 / 2.05 / 0.39 / 50.1 ms | 0.77 / 2.10 / 0.33 / 50.4 ms |
| bench_str scan16k / concat20k / loopsum50m / collatz | 238 µs / 80.8 / 77.3 / 102.5 ms | 231 µs / 80.4 / 80.1 / 104.1 ms |

全部在噪声带内。≤6 参调用的生成代码逐字节不变（结构性保证 + 实测一致）。

## 已知边界 / 遗留

- **A64 栈传参未接**：>8 实参编译期报错（当前语言层无此需求，按需再接，
  方案与 x86-64 同构）。
- **聚合返回值不可间接调用**：无签名信息，返回值按标量处理；要解除需把
  函数值的类型随值携带（vtable 或类型化句柄），与闭包/接口演化同向。
- **闭包 / 捕获仍是红标**（独立条目）：本版只放宽签名，捕获环境另行设计。
