# v2.02 — 标准库解析路径批量提速 + 三个"测不出收益"的实验记录

- 日期：2026-10-24
- 任务：用户要求"继续优化，批量、大量的优化、大改动"。这一版先按数据挑负载：把
  `p0_bench` / `gbench` / `bench_str` / `json_bench` / `find_bench` / `interp_bench`
  全跑一遍，再逐项分离测量（`url_port` / `url_query_get` / `json_parse` / `kv_get` /
  `sha256` / `map` / `s[i]` 下标），只改**测出来有成本**的地方。
- 影响面：标准库（`std/url`、`std/json`、`std/kv` 注释）、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/url.qma` | `url_port`：authority **一遍扫完**（原 `_after_scheme` + `_authority_end` + 找 `@` + 找 `]` + 找 `:` 共 5 遍），端口数字**就地解析**（不再 `substr` + `to_int`）；`url_query_get`：直接在 URL 上扫（不再先 `url_query` 分配一份 query 子串），且只有区间含 `%` 才走 `decode` 比较；新增私有 `_has_pct` |
| `std/json.qma` | `json_parse` 按输入长度**预分配**节点池 / kids / 字节池（上限 26 万节点、4 MB 字节池），省掉解析途中 13 次 realloc 与约 17 MB 拷贝 |
| `std/kv.qma` | 只加注释：`map.get` 对缺失键是 **fail-fast**，`kv_get` 里的 `has` 是语义前提、不是冗余（见"遗留"第 3 条） |
| `docs/06-status.md` | §3.1 的 URL 行改成 58–62 ms；新增 **§3.17 批量微调 A/B 表**（含三个没成实验的完整记录）；§3.16 的 `kv_get` 行注明 `has` 省不掉 |
| `docs/07-gaps.md` | §5：**SHA-256 轮展开 ❌ 已验证无收益**（瓶颈是指令数不是搬移）、**`vec` 窄槽压缩已降级**（全库只有 3 处窄 vec）、新增"URL / JSON 解析路径 ✅ v2.02" |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.02.0` |

## 实测（同机同日，各 3 次取中位，A/B 同一条命令）

| 负载 | 前 | 后 | 倍数 |
|---|---|---|---|
| `url_port` 单次 | 275 ns | **178 ns** | **1.55×** |
| `url_query_get` 单次 | 453 ns | **385 ns** | 1.18× |
| `p0` URL parse × 100k | 74 ms | **58–62 ms** | 1.2–1.3× |
| `json_parse` 1.35 MB | 31 ms / 41 MB/s | **26 ms / 49 MB/s** | **1.19×** |
| `sha256` 1 MiB | 41–42 ms | 41–42 ms | 1.00× |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py`（隔离快照，见下） | **PASS=275 FAIL=0 SKIP=1** |
| `python tests/kv_test.py` | PASS=10 FAIL=0 |
| `python tools/stage0/qlm_cli.py run tests/t45_url.qma` | `ok t45_url` |
| `python tools/stage0/qlm_cli.py run tests/t46_json.qma` | `ok t46_json` |
| `python tools/stage0/qlm_cli.py run tests/t43_sha256.qma` | `ok t43_sha256`（展开版验证用，已回退） |
| `python tools/stage0/qlm_cli.py run tests/t127_kv.qma` | `kv ok` |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | PASS（公开面数字随并行轨的 `pub` 迁移移动，见遗留第 4 条） |

> **回归为什么在快照里跑**：本版收尾时并行轨正在同一工作区改
> `qlm_native.py` / `qlm_pe.py` / `std/net`（`.qla` 目标文件 + 网络栈），工作区里
> `examples/echo_reactor.qma` 会抛 `KeyError: '__memset'`——那是**半写状态**，与本版无关。
> 所以按仓库惯例复制一份 `tools std tests bootstrap examples fixtures bench` 到
> `build/_snap`，把并行轨在改的 8 个文件回退到 `HEAD`，只留本版改动，在那里跑的主回归。

## 已知边界 / 遗留

1. **三个做了但没留代码的实验**（都验证过正确性，都因"测不出收益"回退，理由与数据
   记在 `06-status.md` §3.17）：
   - **SHA-256 8 轮展开**：每轮 8 条搬移全部消失，1 MiB 仍 41–42 ms。瓶颈是**指令数**
     （每块约 3000 条，≈2.8 cycles/条），x86 的 `mov` 在重命名阶段就被消掉。要更快只有
     SHA-NI（本机无）或让 `int` 走 32 位指令（现恒 64 位，掩码消不掉）。
   - **JSON 容器共用暂存缓冲**（去掉每对象一个 `vec[int]`，2 万对象 = 2 万次分配）：
     26 → 27 ms，噪声内。
   - **`vec[u8]` 槽压缩**：盘点发现 `std/` 里窄 vec 只有 3 处（`vec[int]` 339、`vec[str]` 42），
     真实代码吃不到收益 → 从 §5 优先级里降级。
2. **一次真正的错**：`kv_get` 曾改成"先 `get` 再按需 `has`"（基准 190 → 160 ns），但
   `map.get` 对缺失键是 fail-fast，主回归 `[3i3]` 立刻逮到
   （`quelmara: map key not found`）。已回退，并把结论写进 `std/kv.qma`。
   **教训**：库函数"省一次查表"之前，先确认被省掉的那个调用是不是在承担语义。
3. 剩下的性能大头都**不是**微调能解决的：SHA-256/GHASH 要硬件指令、ECDSA P-256 验签
   （25 ms/次）要窗口法重写、`wg_wait` 唤醒粒度要 futex/WaitOnAddress。
   已按"赢回幅度 / 成本"留在 `07-gaps.md` §5。
4. **公开面数字在移动**：并行轨同时在给 `std/*` 补 `pub`（`07-gaps.md` §7.13 的修复），
   公开函数数在本版收尾的几分钟里从 406 → 419 → 425 连续变化。本版只保证
   `03-stdlib.md` 与当时的源码一致；最终口径以 `gen_stdlib_doc.py --check` 的实时输出为准，
   由完成 pub 迁移的那一版回填 `06-status.md` §1。
5. **行尾**：`std/json.qma` 是 CRLF。中途用 Python 整文件读写把 1160 行全刷成了 LF
   （`git diff` 变成 2336 行全文件重写），已转回 CRLF——改已有 `.qma` 用 Edit 或
   `newline=""`，别整文件重写。
6. **并行轨的编号在本版收尾时已跑到前面**：`06-status.md` §1 的公开面行被它标成
   "v2.05 实测"（其 IPv6 / `.qla` 线），而 `docs/versions/` 目录与 `VERSION` 此刻仍以
   v2.02 为最新（`check_docs.py` 的"版本号同源"因此是绿的）。本版只保证自己这一格
   自洽：目录 v2.02 + `VERSION=2.02.0` + 三道门禁 PASS；编号与措辞的最终归并由
   后续提交裁定。
