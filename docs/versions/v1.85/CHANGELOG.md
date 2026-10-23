# v1.85 — `@simd` int 点积：`acc += a[i] * b[i]`（int），四种形状收口

- 日期：2026-10-24
- 任务：`07-gaps.md` §1「`@simd`」🟡 → ✅。补上第四种形状——int 点积，
  使 `@simd` 覆盖 归约×{int,f64} + 点积×{int,f64} 四种语句形状。
- 影响面：语言层（`@simd` 形状识别 + x86-64 发射）、测试、基准、文档

## 为什么不能直接用 `pmulld`

x86 没有 64 位整数 SIMD 乘法：

| 指令 | 问题 |
|---|---|
| `pmulld` | 32×32 → **低 32 位**，高位丢失 |
| `pmuldq` | 只算偶数 32 位通道，且输入截断到 32 位 |
| `vpmullq` | 要 AVX-512DQ，本机（Haswell-EP）没有 |

所以按 `a*b = a_lo*b_lo + ((a_lo*b_hi + a_hi*b_lo) << 32)` 拆成三次
`pmuludq`（32×32 → 64 位无符号，正好是需要的积），再 `psllq` 32 位相加。
**低 64 位与有无符号无关**，结果与标量 `imul` 逐位等价（含 64 位回绕），
不是近似——`tests/t117_simdintdot.qma` 用含负数与大数的向量验证。

## 端口分配是全部收益来源

第一版用 `psrlq` 取高 32 位，实测 972–1056 ns/次（约 1.33×）；
换成 `pshufd` 后 660–670 ns/次（**1.96×**）。同一份算法，1.47× 的差距全在端口：

- `pmuludq` 在 Haswell 上只走 p0，这段每 2 个元素必须发 3 条 → p0 已占 3 拍；
- `psrlq` 也走 p0，再加 2 条就把这段变成单口串行（6 拍/2 元素）；
- `pshufd` 走 p5，与 p0 并行，回到 4 拍/2 元素 = 2 拍/元素。

与 f64 点积的差别：f64 有单条 `mulpd`，int 没有——所以 int 点积的收益主要来自
**跳过逐元素越界检查**，不是来自并行度。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `@simd` 点积分支新增 int 形态：`pshufd`×2 拆高低 32 位 + `pmuludq`×3 + `psllq` + `paddq`，两路展开 |
| `tests/t117_simdintdot.qma` | **新增**：int 点积正例，与标量版逐位对拍（含负数、大数、回绕） |
| `tests/bad/simd_dot_mixed.qma` | **新增**：两数组与累加器类型混写 → 语句级注解下编译报错 |
| `tests/run_win_tests.py` | 自校验组注册 `t117_simdintdot` |
| `bench/idot_bench.qma` | **新增**：标量 vs `@simd` 同数据对拍（1024 元素，5 轮 × 2000 次取最小） |
| `docs/02-language.md` | §8.2 形状表加第四行 + int 点积的三条口径（低 64 位等价、端口分配、与 f64 的区别） |
| `docs/06-status.md` | §3.4f：1295–1349 ns → 660–670 ns，1.96× |
| `docs/07-gaps.md` | §1「`@simd`」🟡 → ✅ v1.85；§5 把"AVX2 点积"改写为"int 点积加宽（4 通道 / 32 位元素）"并给出三条前置条件 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=233 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run tests/t117_simdintdot.qma --target win` | 与标量版逐位一致 |
| `python tools/stage0/qlm_cli.py run bench/idot_bench.qma --target win` | 标量 1295–1349 ns/次，`@simd` 660–670 ns/次，**1.96×** |

### 补充证据：双向 .qex 对照 + 反汇编（隔离 worktree 复核，v1.97 回归确认）

上面三行是"能跑、数对"。要证明**发射层没被这次改动波及**，靠的是产物逐字节比对
（本机 VBS 噪声 ±50%，哈希没有噪声）。工具：`python tools/dev/qexcmp.py <基线树> <本版树>`。

| 项 | 结果 |
|---|---|
| 语料 | 161 个源文件（`tests/` + `examples/` + `bench/`） |
| 双向 `.qex` 对照 | **SAME=152 / DIFF=0 / NEWFILE=2 / BOTHFAIL=7** |
| 基线 fail-fast 探针 | 把 `idot_bench.qma` 拷进干净基线树再编 → `@simd 点积目前只支持 f64（int 点积需 SSE4.1 pmulld，未接）` |

读法：

- **SAME=152**：两边编出的 `.qex` 逐字节相同——不是"看起来没变"，是 sha256 相同。
- **DIFF=0**：没有任何"两边都能编"的文件产物变了。
- **NEWFILE=2**：`tests/t117_simdintdot.qma` / `bench/idot_bench.qma` 是**本版新增的源文件**，
  基线树里没有；这一格**不是** fail-fast 证据（工具第一版把"文件不存在"与"基线拒绝编译"
  混成一个 `ONE`，会误读，已分列）。
- **BOTHFAIL=7**：`tests/bad/*` 与依赖网络/多核配置的 examples，两边同样失败。

反汇编对照（`t117` 编出的 `.qex`，capstone 读 `.text`，向量段整段）：

```
1272: movdqu xmm1, [r11 + rcx*8]     ; a[2i], a[2i+1]
127c: movdqu xmm2, [r10 + rcx*8]     ; b[2i], b[2i+1]
1286: pshufd xmm3, xmm1, 0xf5        ; a_hi（p5）
128b: pshufd xmm4, xmm2, 0xf5        ; b_hi（p5）
1290: movdqa xmm5, xmm1
1294: pmuludq xmm5, xmm4             ; a_lo*b_hi
1298: pmuludq xmm1, xmm2             ; a_lo*b_lo
129c: pmuludq xmm3, xmm2             ; a_hi*b_lo
12a0: paddq  xmm3, xmm5
12a4: psllq  xmm3, 0x20
12a9: paddq  xmm3, xmm1
12ad: paddq  xmm0, xmm3              ; 累加
12b1: add    rcx, 2
12b5: jmp    0x1261
```

12 条/2 元素，p0 只有 4 条（3×`pmuludq` + 1×`psllq`），p5 两条 `pshufd`——
与"port 0 打满"的分析逐条对上。v1.97 上复核：`t117` 仍绿、fail-fast 仍生效，
这段反汇编**逐条相同（连地址都没变）**，说明 v1.86–v1.97 的重构没有动到这条路径。

## 已知边界 / 遗留

- 仍**不是向量化器**：只认四种语句形状，其余循环原样走标量。
- 2 通道 + 3×`pmuludq` 打满 port 0，是本机（无 AVX2）的上限；加宽到 4 通道需要
  AVX2 且只对 32 位元素成立（`vpmullq` 要 AVX-512DQ），已转 `07-gaps.md` §5。
- 32 位元素特化还依赖 `vec`/数组的**槽压缩**（现在 `[N]i32` 也是 8 字节槽）。
