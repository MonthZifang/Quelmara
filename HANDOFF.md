# Quelmara 交接文档

> 生成时间：2026-11-01 03:45（Asia/Shanghai）
> HEAD：`9f32168`（v3.58）→ v3.59 待提交
> 这份文档面向"接手继续做"的人，只写**现在在哪、下一步做什么、有哪些坑**。

---

## 1. 一句话现状

qlmc（用 Quelmara 写的 stage-1 编译器）对 `std/` 的覆盖率：

| 状态 | 覆盖率 | 说明 |
|---|---|---|
| 已提交（v3.58） | 60 / 70 | HEAD `9f32168` |
| **v3.59（本次）** | **63 / 70** | 代码 + 夹具 + 文档 + 门禁全部就绪，待提交 |

**v3.59 已经走完全部流程**：14 个 SIMD 内建、差分夹具 `s36_aes`（18 行逐字节
一致）、CHANGELOG、`BASELINE` 60 → 63、`VERSION` 3.59.0、6 个文档门禁全过、
自举 30/30 + 不动点成立。

---

## 2. 下一步

### 2.1 先确认 v3.59 提交了

```bash
cd C:\Users\43551\Desktop\Quelmara
git log --oneline -3          # 应该看到 v3.59
git status --porcelain        # 应该干净

# 如果还没提交：
python tests/run_win_tests.py       # 全量回归
git add -A
git -c core.safecrlf=false commit -F <msgfile>
python build/push_via_api.py 9f32168 HEAD
python build/_verify_push.py        # 必须 TREE MATCH
```

### 2.2 v3.59 做了什么（参考）

**新增 14 个 SIMD 内建**，一次解开 3 个模块（`std/aes`、`std/tls13`、
还有一个此前卡在同一处的）：

| 内建 | 编码 | 类型 |
|---|---|---|
| `pand` | `66 0F DB /r` | 两字节 |
| `por` | `66 0F EB /r` | 两字节 |
| `pshufb` | `66 0F 38 00 /r` | 三字节（SSSE3） |
| `aesenc` | `66 0F 38 DC /r` | 三字节（AES-NI） |
| `aesenclast` | `66 0F 38 DD /r` | 三字节（AES-NI） |
| `pclmulqdq` | `66 0F 3A 44 /r ib` | 三字节 + imm8 |
| `psrlw` | `66 0F 71 /2 ib` | 立即数移位 |
| `psllw` | `66 0F 71 /6 ib` | 立即数移位 |
| `psrlq` | `66 0F 73 /2 ib` | 立即数移位 |
| `psllq` | `66 0F 73 /6 ib` | 立即数移位 |
| `pslldq` | `66 0F 73 /7 ib` | 立即数移位 |
| `psrldq` | `66 0F 73 /3 ib` | 立即数移位 |
| `cpu_aes` | CPUID.1:ECX[25] | 特征探测 |
| `cpu_pclmul` | CPUID.1:ECX[1] | 特征探测 |

**新增 2 个 IR 节点**：`OP_XMMRI = 84`（三字节 map + imm8）、
`OP_XMMSH = 85`（立即数移位）。

**新增 2 个编码函数**：`_sse_rr3`（三字节 map）、`_sse_shift_imm`（`/group ib`）。

**新增 1 个运行时例程**：`RT_CPUID1ECX = 29`（`_gen_cpuid1ecx`），
**必须保存 RBX**（`cpuid` 会写它，而 RBX 是 Win64 非易失寄存器）。

**踩到并解决的坑**：`_lower_builtin` 被 14 个新分支顶到 **417 槽 > 416 上限**，
自举 stage-2 立刻失败。修法是抽出 `_lower_simd_extra` 独立函数。

---

## 3. 剩余 7 个模块（63 → 70）

| 模块 | 缺口 | 难度 |
|---|---|---|
| `std/csv.qma` | `vec[vec[T]]` 类型码撞区间（§7.18） | **高** —— 架构性 |
| `std/gen.qma` | 泛型 `[T: Ord]` | **高** —— 需要单态化 |
| `std/http.qma` | `函数重复定义 _fail` | 中 —— 需要重构 |
| `std/logfile.qma` | `函数重复定义 _get` | 中 —— 需要重构 |
| `std/park_linux.qma` | `syscall` 内建 | 低，但 **Linux 专用**（Windows 上意义有限） |
| `std/httpc_net.qma` | `未知类型 TlsClientResult` | 中 —— 跨模块 struct |
| `std/tls_net.qma` | 同上 | 中 —— 跨模块 struct |

**优先做 `TlsClientResult`（+2 模块，63 → 65）**：v3.59 解开了 `std/tls_client`
的 SIMD 依赖之后，它**不再是死结** —— 现在是真正的跨模块 struct 类型问题。
参考 v3.52 的跨模块 const 三段式解析（`_prescan_imports` / `_prescan_consts`）。

---

## 4. 必读：这个项目的五个反复出现的坑

这些都是**用整版时间换来的教训**，接手时务必先读。

### 4.1 帧槽 416 上限（踩过 5 次）

`_lower_builtin`、`_emit_ir`、`build_rdata`、`main` 这些大函数**贴着 416 槽上限**。
往它们里面加任何代码，都可能让自举 stage-2 编不过自己。

**规则**：给这些函数加逻辑前，先抽独立函数。加完立刻跑
`python tests/bootstrap_test.py --strict`。

### 4.2 常量编号撞车（踩过 3 次）

- `I_CREATE` 其实是 `CreateThread`（v3.48 才发现）
- `_op_name` 表错位（v3.45）
- `S_FOREACH = 19` 撞 `S_BREAK = 19`（v3.50）

**规则**：加新 opcode / IAT 槽 / 语句编号后，用
`Select-String '^const S_'`（或 `OP_` / `I_`）**全表核一遍**。编号区间不连续，
"看着空"不等于真的空。

### 4.3 静默错编（最难抓）

不崩、不报错、结果错。典型例子：

- `map.del` 直接清键 0 → 切断探测链 → 后面的键**找不到但数据还在**（v3.55）
- 端口字节序拆反 → `sendto` 返回正常但包发错端口（v3.49）
- `_len_of` 缺 SIB 字节 → 只在寄存器分到 R12 时崩（v3.51）

**规则**：改语义的改动**必须有差分测试**（stage-0 vs qlmc 逐字节比），
"能编过"说明不了任何事。

### 4.4 `_ir_emit` 的 `a` / `b` 必须是合法 vreg

`_ir_emit` 里 `if a > 0 { fc.vend.set(a, i) }` —— 塞槽号 / 操作码 / 立即数
会直接 `vec index out of bounds`。

**规则**：额外数据全部塞 `imm`（它不参与 vend 写入）。

### 4.5 诊断粒度

怀疑某个函数时，**在函数体内逐句打点**，不要只在入口/出口打 ——
入口打点只能证明"进来了"，证明不了"哪一句炸的"（v3.58 在这上面多花了两轮）。

---

## 5. 工作流约定

### 5.1 一个版本 = 一次完整流程

```
改代码 → 重建 qlmc（约 2.5 分钟）
       → 验证功能
       → python tests/bootstrap_test.py --strict（必须 30/30 + 不动点）
       → 写差分夹具 + 注册进 tests/qlmc_test.py
       → python tests/run_win_tests.py（全量回归）
       → 6 个文档门禁
       → 写 docs/versions/vX.Y/CHANGELOG.md
       → 改 VERSION + 上调 BASELINE（如果覆盖率涨了）
       → 更新 docs/06-status.md（加 §3.10x 小节）
       → 提交 → 推送 → 验证 TREE MATCH
```

### 5.2 数字的单一出处

**实测数字只能写在两处**：
- `docs/06-status.md`
- `docs/versions/*/CHANGELOG.md`

其它文档（尤其 `07-gaps.md`）必须写"见 `06-status.md`"。
`check_docs.py` 会拦住违规。

### 5.3 推送

`git push` 不通（SSH 被拒）。用：

```bash
python build/push_via_api.py <parent_sha> HEAD
python build/_verify_push.py      # 必须 TREE MATCH
```

API 建的 commit SHA 与本地不同（committer 由服务端填）**是正常的**，
只要 tree 一致就对。

### 5.4 已知的偶发失败

`tests/debugger_test.py` 的"[3] 调试信息不改变程序行为"偶尔 FAIL
（`r1.stdout != r2.stdout`）。根因是 `build_demo(dbg=True)` 可能回退到
`_build_dbg_direct()`（两条构建路径）。**与编译器改动无关**，重跑通常就好。

---

## 6. 当前基线数字（用于判断有没有退化）

```
主回归          PASS=370 FAIL=0 SKIP=0
qlmc 差分       PASS=84 FAIL=0
覆盖率          63/70
自举            30/30 + 不动点成立
stage-2 产物    658432 B
ARENA_CAP       4 MB（stage-2 用量约 660 KB，余量充足）
```

---

## 7. 建议的下一步顺序

1. **做 `TlsClientResult` 跨模块 struct**（+2 模块，63 → 65）
   - 参考 v3.52 的跨模块 const 三段式解析（`_prescan_imports` / `_prescan_consts`）
   - 现在 `std/tls_client` 已经能编，不再是死结
2. **重构 `std/http` / `std/logfile` 的重复定义**（+2，65 → 67）
   - 需要先看 qlmc 为什么不允许重复定义、以及那两个模块为何真的重复
3. **最后三个大件**（`vec[vec[T]]` / 泛型 / `syscall`）留给专门的版本

---

## 8. 有用的脚本（`build/` 下，都是临时工具）

| 脚本 | 用途 |
|---|---|
| `push_via_api.py` | 推送（必需，git push 不通） |
| `_verify_push.py` | 验证远端 tree == 本地 tree |
| `_opscan.py` | 扫 OP 编号空间，找空缺（避免撞车） |
| `_opnames_check.py` | 检查 `_op_names_str` 条目数 |
| `_fnuse3.py` | 量每个函数的 arena 用量（查"编译缓冲不够"） |
| `_scan_args2.py` | 定位源码里所有 `args(` 命中（v3.56 用过） |

这些都是**一次性诊断脚本**，可以随时删或重写。
