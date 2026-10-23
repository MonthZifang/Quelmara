# v1.60 — `@simd` f64 点积形状：`acc += a[i] * b[i]`（语言层黄标收窄）

- 日期：2026-10-23
- 任务：语言层 §1「`@simd`」行 🟡 收窄——新增第三种形状：**f64 点积**
  `acc += a[i] * b[i]`（SSE2 `mulpd` 两通道 + `addpd` 累加 + 标量尾）。
  与 v1.48（defer）同属 §8 语言层黄标逐项序列。
- 影响面：`tools/stage0/qlm_native.py`（`mulpd`/`mulsd` 发射器、`vdotd` 伪指令
  IR + 序列化 + 发射、`lower_simd_for` 形状识别）、`tools/stage0/qlm_opt.py`
  （`vreg_mentions` 登记 + `_EFF` 副作用表）、`tests/t96_simddot.qma`（新增）、
  `tests/run_win_tests.py`（注册）、`bench/dot_bench.qma`（新增）、
  `docs/02-language.md`（§8.2）、`docs/07-gaps.md`（§1 行）、
  `docs/06-status.md`、`tools/stage0/qlm_cli.py`（VERSION）

## 为什么是它

§8 语言层黄标顺序里 `@simd` 形状紧随 defer。原实现只认单数组归约
`acc += a[i]`（int `vsum` / f64 `vsumd`）；点积被登记为"需 AVX2 `vpmullq`"。
本机 CPU 无 AVX2（06-status 环境节），但 **SSE2 就能做 2 通道 f64 点积**：
`movupd` 两路非对齐读 + `mulpd` + `addpd` 累加，标量尾 `mulsd`/`addsd`。
不依赖新指令集、本机可测可跑分，属"黄标里能立刻收窄的一项"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 发射器补 `mulpd`（66 0F 59）/`mulsd`（F2 0F 59）；IR 新增 `vdotd`（dst, baseA, baseB, count）并登记序列化；发射序列与 `vsumd` 同构（RCX 下标步 2、R11=baseA、R10=baseB、R8=count 且 push/pop 保护、xmm0 累加 / xmm1,xmm2 两路读）；`lower_simd_for` 识别 `acc += a[i] * b[i]` 与 `acc = acc + a[i] * b[i]` 两种写法，校验两数组同长定长、元素与累加器均 f64（int 点积 fail-fast：SSE2 无 64 位乘法） |
| `tools/stage0/qlm_opt.py` | `vreg_mentions` 登记 `vdotd`（dst + 3 个源 vreg）；`_EFF` 副作用表加入 `vdotd`（读两段内存，不可被调度器跨访存重排——与 `vsum`/`vsumd` 同纪律） |
| `tests/t96_simddot.qma` | **新增**：向量段（8/12 元素）、标量尾（1/3/5 元素）、两种赋值写法、与标量逐位相等（测试值全部精确可表示）、零向量/空区间、性能环（min of 5） |
| `bench/dot_bench.qma` | **新增**：1024 f64 点积，标量 vs `@simd` 各 2000 次，ns/次 + 加速比 |
| `docs/02-language.md` | §8.2 标题"两种形状"→"三种形状"；形状表加点积行；原"点积需 AVX2 未做"改为"f64 点积已接（SSE2 两路），int 点积需 SSE4.1、AVX2 4 通道留待"；证据行补 t96 + dot_bench |
| `docs/07-gaps.md` | §1 `@simd` 行：补 f64 点积（v1.60，4.6×），int 点积/AVX2 仍缺 |
| `docs/06-status.md` | 主回归 PASS 数字 + §3.4 SIMD 节点积行 |

## 实现要点

- **寄存器账**：`vsumd` 用 R11(base)/R10(count)/RCX(下标)/RDX(临时)/RAX(ACC)。
  点积多一个 baseB：R10 让给 baseB，count 移 R8 并在序列两侧 `push`/`pop`
  保护（R8 非池寄存器、序列内无调用，按 cpuid 族纪律显式保护）。
- **标量尾与 `vsumd` 完全同构**：向量段退出后 `movhlps`+`addsd` 把两路部分和
  折半，再逐元素 `mulsd`/`addsd`；每步 `movq_rx(ACC, 0)` 同步（v1.16 建立的
  模式，非 SSA 尾部的既有纪律）。
- **AArch64**：`vdotd` 未被 A64 发射器识别 → 编译期 `A64 无法发射` fail-fast
  （irdiff 记 SKIP，与 t85 的 `trunc` / t86 的 map 聚合值同模式）。
- **C 后端**：`@simd` 整体不进 C 交叉验证（既有边界），C 链不受影响。

## 验证

- `tests/t96_simddot.qma`：全部断言通过（含与标量逐位相等）。
- `bench/dot_bench.qma`：1024 f64 点积 **2479 ns → 539 ns（4.59×）**，
  两路和逐位相同（85942000）。
- 主回归 / lexdiff / parsediff / bodydiff / irdiff（t96 记 SKIP）/ emitdiff /
  三禁全绿（数字见 06-status.md）。
- 性能双向对照：v1.56 基线 worktree 与本树各编 p0_bench / gbench / bench_str，
  三个 `.qex` 逐字节相同——点积改动对既有形状零影响。

## 同版并入：泛型 struct（语言轨，红标 → 黄标）

> 同一工作区两条轨并行提交，本版把泛型 struct 一起收口（`tools/stage0/qlm.py`
> 与 @simd 的 `qlm_native.py` 零文件重叠）。

- `struct Box[T] { value: T }` + `Box[int] { ... }`：**解析期单态化**，现场合成
  普通结构体 `Box__int`，布局/字段偏移/值语义/聚合返回 ABI 全部复用既有路径，
  后端零改动。多类型参数、`vec[T]` 等容器字段、嵌套实例 `Box[Box[int]]`、
  形参/返回值位置全部可用。
- fail-fast：裸写 `Box`、容器实参 `Box[vec[int]]`、实参个数不符、模板字段里嵌套
  泛型 struct 一律编译期报错。
- 测试：`tests/t99_generic_struct.qma`（20 断言）+ `tests/bad/gstruct_*.qma`（3 个负向）。
- 自举 parser 不做单态化 → `tests/parsediff.py` 把 t99 记入 PARSE1_PENDING（显式记账）。
- 07-gaps：`泛型 struct / 泛型方法` 行 ❌ → 🟡（泛型方法 / impl 泛型 / 泛型 enum 仍未做）。
