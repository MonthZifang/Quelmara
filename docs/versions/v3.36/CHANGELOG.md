# v3.36 — 给 stage-1 编译器补 5 个内建，`std/` 覆盖率阻塞项从 35 降到 12

- 日期：2026-10-30
- 任务：用户要求"`tools/stage0/*.py` 里的编译器核心全部改用自研语言"
- 影响面：**核心（Quelmara 源码）** `bootstrap/qlmc/qlmc.qma`
  （5 个内建 + 1 个新 opcode + 32 位加载支持），新增夹具
- 版本：按 `00-convention.md` §5.1 建版本目录

## 先说清规模

用户的要求是"编译器核心全部改用自研语言"。这不是一次能做完的：

| 项 | 规模 |
|---|---|
| `tools/stage0/*.py` 总量 | 21 文件 / 约 30 000 行 |
| 其中编译器核心（native + 前端 + 优化） | 约 21 000 行 |
| 已有自研实现 `bootstrap/qlmc/qlmc.qma` | 10 377 行（子集 S20） |
| **qlmc 对 `std/` 的覆盖率** | **0 / 70** ← 硬指标 |

所以这一版不喊口号，而是**先测出阻塞项，再逐个消除**。

## 起点：测出 qlmc 编 `std/` 的真实阻塞

跑一遍全部 70 个模块，按错误分类：

| 数量 | 原因 |
|---|---|
| 17 | `未定义函数 str_from_bytes` |
| 16 | 没有 main（需 lib 模式） |
| 9 | `未定义函数 static_word` |
| 4 | `未定义函数 mem_ptr` |
| 2 | `未定义函数 str_alloc` |
| 其余 | `mem_chr` / `mem_load32` / `xmm_load` / 类型码撞区间… |

**35 / 70 是缺内建** —— 这不是语言能力问题，是 qlmc 的内建表不全。

## 补的 5 个内建

### 1. `str_from_bytes(v: vec[int]) -> str`（最大项，17 个模块）

**签名容易搞错**：它收的是**一个 `vec[int]`**，不是 `(p, n)`。语义是
每个元素占 8 字节槽、**只取低字节**拼成串（见 `qlm_native.py` 的
`__str_from_bytes`）。

第一版我按 `(p, n)` 实现，结果 std/cookie 等模块编译时 qlmc 自己
`vec index out of bounds` —— 因为调用点只传了 1 个实参。

### 2. `static_word(i) -> int`（9 个模块）

std/ 的 log / timer / reactor / sync 靠它把状态放在回调能读到的
进程级位置。

**qlmc 的 .bss 只有 32 字节**（游标/锁/堆基址/上限），放不下静态字区。
两个方案：从堆惰性分配（要多一个"已分配"标志 + 分支），或**扩 .bss**。
选后者 —— .bss 本来就零初始化，正好是静态字要的语义：

```quelmara
const STATIC_SLOTS = 64
const STATICW_BSS_OFF = 32
const BSS_SIZE = 32 + STATIC_SLOTS * 8
```

地址 = `&bss[STATICW_BSS_OFF] + i*8`。为此新增 `OP_BSSADDR`
（与 `OP_LEA` 同构，只是重定位类型从 `FK_STR` 换成 `FK_BSS`）。

**踩的坑**：第一版写成 `_ir_emit(fc, OP_BSSADDR, base, STATICW_BSS_OFF, 0, 0)`，
把偏移放进了 `a` 槽（被当 vreg 计数），导致 qlmc 自己崩溃。正确是放 `imm`。

### 3. `mem_ptr(p, off) -> int`（4 个模块）

纯指针算术 `p + off`，返回值不带类型标记。直接 `OP_ADD`。

### 4. `mem_load32(p, off) -> int`（4 个模块）

**两个坑**：

* **第 2 个参数是字节偏移，不是 4 字节下标**（与 `mem_load64` 的
  "第 w 个字"不同！）。实测 `mem_load32(q,1)` 读的是从偏移 1 开始的 4 字节。
* **`OP_LOAD` 的发射忽略宽度**，无条件发 8 字节 `mov` —— 所以第一版
  读到 8 字节，高 32 位是脏的，差分立刻对不上。

修法：新增 `_mov_load32`（REX 不带 W，`mov eax,[mem]` 会零扩展高 32 位），
并让 `OP_LOAD` 按 `imm` 分派宽度。

### 5. `str_alloc(n) -> str`（2 个模块）

分配长度 n 的可写空串，**长度头写 n**（不是 0），末尾 NUL。返回数据指针。

## 结果

| 指标 | 前 | 后 |
|---|---|---|
| 缺内建导致的失败 | 35 | **12** |
| qlmc 自身崩溃（vec 越界） | 11 | **0** |
| `static_word` 相关失败 | 9 | **0** |
| `str_from_bytes` 相关失败 | 17 | **0** |

`std/` 覆盖率仍是 0/70，但**剩余阻塞已经换了一类**：现在最大项是
"没有 main（需 lib 模式）" 30 个 —— 那是**功能缺失**（qlmc 只做 program
不做 lib），不是内建缺失。

## 夹具

`tests/t180_qlmc_builtins.qma`，重点验边界而不是"能跑"：

* `static_word` 不同槽互不干扰、初始为 0、覆盖写不影响别的槽；
* `str_from_bytes` 取**低字节**（`0x141` → `'A'`，高位必须丢掉）；
* `str_alloc` 长度头是 n、可写、末尾有 NUL；
* `mem_ptr` 偏移 0 与原指针同址、偏移 8 字节 = 第 1 个字；
* `mem_load32` 的偏移是**字节**单位、零扩展不读到符号位。

**关键验证**：这个夹具用 stage-0 编一遍、用 qlmc 编一遍，
**两边产物行为必须一致**。第一次跑 qlmc 版本时 `mem_load32` 就挂了，
正是靠这个对拍发现宽度没分派。

## 回归

全量 Windows 回归 PASS=352 FAIL=0 SKIP=0（v3.35 是 351，新增 1 条）。

自举链全绿：`qlmc_test` 68 项、`parsediff` 234 项、
不动点 stage-2 == stage-3。

## 遗留与下一步

**最大阻塞已变成 lib 模式**（30 个模块只是"没有 main"）。这是下一版
最该做的：qlmc 加 `lib` 模式（不要求 main、导出符号），能立刻把
30 个模块从"失败"变成"能编"。

之后是 `mem_chr` / `mem_xchg` / `mem_diff` / `xmm_load` 等剩余内建，
以及 §7.18 的 `vec[vec[T]]` 类型码撞区间（那条 stage-0 也有，是共同缺口）。

**距离"核心全部用自研语言"还很远**：qlmc 10 377 行 vs stage-0 约
21 000 行核心。这一版的贡献是把"内建缺失"这一类阻塞清掉了，
让下一版能直接面对功能缺口（lib 模式、类型系统）而不是零碎的原语。
