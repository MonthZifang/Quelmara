# Quelmara 交接文档（HANDOVER）

> 工作区状态（2026-10-22）：**已发布 v1.17g**——今天一天从 v1.12 推进到 v1.17g
> （24 个 commit，已推送 GitHub 远端 master `68b8550`）。  
> 各版本特性、修复与回归项数的**权威记录**在 `CHANGELOG.md`；本文只保留  
> 当前快照、接力记忆与下一步排期，不再按轮复述。  
> **完整能力边界（含"文档与代码不符"逐条核对、标准库缺口全表、优先级路线）见 `docs/GAPS.md`。**  
> **性能跑分与方法论权威在 `docs/PERF.md`**；**src/ 三类资源布局见 `docs/SRC.md`**；  
> **P0 四件套 API 与实测见 `docs/P0_LIBS.md`**。  
> **工具链分层**：`tools/stage0/` 是 Python 引导层（待退场），`bootstrap/` 是 Quelmara 自举层，  
> `tests/`、`tools/dev/` 允许长期用 Python/Node。分层纪律见 `docs/SELFHOST.md`。  
> 本机（Windows）验证边界：PE 链可执行级验证；[7] 交叉验证与 native/C 链需 Linux/WSL  
> （本机无 gcc/clang，`wsl.exe` 被沙箱拉黑）。

## 0.0 AI 接力包（记忆注入 · 下个会话先读这一节）

> 这一节是给"接手的 AI"看的：把当前状态、已验证的事实、踩过的坑、不能违反的约定一次写清，
> 避免重新探索、避免重复犯错。**读完这一节再动代码。**

### 身份与坐标

<!-- legacy-ok:begin -->
- 项目：**Quelmara**（旧名 Rosoto，仓库目录仍是 `Rosoto/rosoto/`，改名脚本见 §6）。
<!-- legacy-ok:end -->
- 语言定位：自研系统级语言，**产品后端只允许自研**（x86_64 ELF / PE32+ / AArch64），
  C99 后端只做交叉验证，**永远不是产品链路**。
- 宿主环境：Windows，用户 `43551`；CPU 是 **Xeon E5-2666 v3（Haswell 代，无 SHA-NI/AVX2）**；
  本机只能跑 PE 链；`wsl.exe` 被沙箱拉黑（`[7]` 交叉验证永远 SKIP）。
- 解释器：`C:/Users/43551/.workbuddy/binaries/python/versions/3.13.12/python.exe`
  （capstone 反汇编装在 `envs/default` venv 里——调试编码问题时用那个）。
- 本机 VBS/Hyper-V 开着，bench 噪声 ±50%——**所有跑分必须 min-of-3/5**
  （`bench/*.qma` 已内置）。

### 当前状态（2026-10-22 实测，不是文档抄的）

| 项 | 数字 | 命令 |
|---|---|---|
| PE 回归 | **124 项全绿**（FAIL=0，SKIP=1 WSL） | `python tests/run_win_tests.py` |
| 自举 | **2/9**，1846 / 21114 行 = 8.0%（总行数随 std 增长） | `python tools/dev/selfhost_status.py` |
| 函数体对拍 | dump 一致 **740** / 分叉 625 / SKIP 不同步 18 | `python tests/bodydiff.py` |
| 词法 / 声明对拍 | 109/109、94/94 | `tests/lexdiff.py` / `tests/parsediff.py` |
| 三件门禁 | check_names / check_origin / check_docs 全 PASS | `tools/dev/check_*.py` |
| zlib 互操作 | gzip 7/7 样本逐字节一致 | `tests/run_win_tests.py` 内 |
| 远端 | GitHub `MonthZifang/Rosoto` master = 本地 `364bbba` | `tools/dev/push_via_api.py` |

### 性能现状（全部通用优化，min-of-N，无 benchmark 特调）

| 项目 | v1.11 起点 | **现状（v1.17f）** | 提升 | vs 竞品（同机） |
|---|---|---|---|---|
| crc32 1MiB | ~17ms | **1-2ms**（slice-by-4 + mem_load32） | **~10×** | ✅ zlib 级 |
| gzip 1MiB | 117ms | **26ms**（盲比否决 + slice-by-4） | **4.5×** | ✅ zlib -6 是 15-25ms，**基本追平** |
| split+join 1MiB | 29ms | **9ms** | 3.2× | Go 5ms，差 1.8× |
| JSON parse | ~4ms/93KB | **41 MB/s**（raw 化） | 1.8× | Go ~100MB/s 级 |
| url parse×100k | 92ms | 73ms | 1.26× | — |
| SHA-256 1MiB | 68ms | 65ms | 持平 | OpenSSL 差 20×——**唯一路线是 SHA-NI**（基础设施已就绪，本机 CPU 无硬件） |
| @simd 归约 | 无 | int（paddq）+ **f64（addpd）** | 3-4× | — |
| loop_sum 200M | 12.6 c/iter | **10.8 c/iter** | 1.17× | GCC ~3.5，差 3×（编译器三件套待做） |
| 分配器 | — | 热路径 7 条指令 | — | 已是最优形态（推演记录 PERF.md） |

### 本轮（2026-10-22，v1.12→v1.17g）落地清单

| 主题 | 内容 | commit |
|---|---|---|
| v1.12 | vec[vec[T]] 嵌套容器 | `1467575` |
| v1.12.1 | Windows args() token 长度多算 1（--body 模式恒 false 的根因） | `640b73d` |
| v1.13 | 自举函数体 parser 四个系统性 bug（定界符遗留/赋值判定/assigni 协议/nm 污染）——dump 一致 127→653 | `b11ee44` `5586774` |
| v1.14 | 性能三件：CRC 查表 / DEFLATE 滚动哈希 / **bounds_elim 等值类**（str/vec 循环 bounds 全消，库代码零改动受益） | `391476e` |
| v1.14b | str_alloc/str_from_mem/mem_ptr 原语 + str+int 编译期报错 + split/join/url 批量化 | `f12eb1c` |
| v1.14c | **qpm 包管理器 v0**（install/add/remove/list，path+git 依赖，lock.toml） | `4f8a5cf` |
| v1.15 | **SHA-NI 基础设施**：cpu_sha 内建（cpuid leaf7 EBX[29]）+ XMM/SHA 指令族 + xmm 槽负数编码 + 五处登记 | `4ac04ac` |
| v1.16 | **std 五件套**：sleep_ms / fs 最小集 / std/rand / std/sort / std/log | `41c0e0c` |
| v1.16b | **@simd f64 归约**（addpd）修复落地 + **编译期死循环检测**（guard 不更新→警告+位置） | `1d4d5ea` |
| v1.17 | **src/ 三类资源布局**（lib/ref/asset）+ read_asset 内建 + docs/SRC.md | `8133c7b` |
| v1.17b/c | std 库生态（ds/serialize/timer/wall_ms/**UDP 四件**）+ UDP 五连修全链路打通 | `2d37fbf` `cf3dfe5` |
| v1.17d | **全局 DCE**（main 调用图可达性，95→3 fns，二进制 10.2×） | `871001e` |
| v1.17e/f | JSON raw 化（41MB/s）+ gzip 盲比否决 + mem_load32 + slice-by-4（**追平 zlib**） | `c4d1898` `a50a416` |
| v1.17g | pool_* 指针式对象池 + log_kv 结构化字段 | `364bbba` |

### 语言层的"写库须知"（用血换的，写标准库/内建前必读）

**str ABI 与指针（v1.14 起最重要的约定族）：**
- str 值 = **数据指针**（int 形态），len 头在前 8 字节；`str_alloc(n)`/`str_from_mem(p,n)`
  是正规批量构造器；批量拼接一律 mem_copy，禁止逐字节 push。
- **`s + n` 会被 str 拼接劫持**（v1.14 起 str+int 直接编译报错）——指针算术用 `mem_ptr(p, off)`。
- **global 字符串（`("ga", gid)`）传给 str 函数前必须 +8 成数据指针**——直接传会让
  concat 读到垃圾 len 巨量分配（read_asset 踩过，heap 超限）。
- **`intern_str` 是 winapi 用的无 len 头 C 串；参与 str 拼接的必须 `intern_str_lit`**
  （[len][bytes][NUL] 语言层布局）——两者混用就是上面的惨案。

**winapi / 网络内建（v1.17c 五连修全记录）：**
- **winapi 返回 32 位值（RAX 高 32 为 0）**：INVALID（0xFFFFFFFF）≠ 符号扩展的 -1，
  先 `shl 32 / sar 32` 符号扩展再比较。
- **失败处理器不能挡成功路径**：`jnz b, lf` 后紧跟 `label lf`+fail——成功 fall-through
  穿进 exit。**fail 块必须放 ret 之后**（TCP 版用 jz+fail 在 ret 后所以没踩）。
- **有副作用的调用，结果必须被消费**：WSAStartup 结果未使用 → 优化器删除 → socket 恒
  SOCKET_ERROR（"UDP 全链路代码正确却恒失败"的真凶）。
- **sockaddr_in 是字节紧排**（family@0/port@2/addr@4/zero@8），不是一字段一 8B 槽；
  slot0 = `2 | (htons(port)<<16) | (ip<<32)`，ip 用 udp_parse_ip 的内存序约定。
- ws2_32 导入函数必须在 `qlm_pe.py WS2_32_FUNCS` 白名单——漏了就归 kernel32 →
  0xC0000139 加载即崩。
- NUL 终止符写在数据**末尾**（offset = r+8），不是开头。

**IR / 优化器纪律：**
- **新增 IR 指令五处登记**（漏一处就是"开优化才错"的静默误编译）：
  `vreg_mentions`、`_subst_vregs`（漏它 = 悬空 vreg 段错误）、`_map_ins`、`PURE`、
  `_EFF`（访存类不可挪过 call）+ `_LAT` + gen（x86 + AArch64 明确 fail-fast）。
- xmm 槽用**负数编码 -(x+1)**（v1.15）与 vreg 正数空间隔离。
- `mem_load64/store64` 偏移是**槽索引（×8）**；`mem_load8/mem_load32` 是**字节偏移**
  （scale 0）——mem_load32 首版用 scale 3 读出 8 倍远的垃圾。
- 有副作用的 winapi/syscall 在优化器眼里"结果未使用即可删"——**错误检查本身就是消费**。
- `vec` 句柄经 `int` 形参/返回值传递会丢类型标签；方法调用不能链在函数调用结果上；
  64 位右移用 `>>>`（`>>` 灌符号位）；`"\xNN"`（≥0x80）是原始字节。
- **f64 数组元素类型传播**：[N]f64 元素按位模式存储，index 降级必须 mark float——
  否则 `acc += a[i]` 把位模式当 int 走 i2f64（1.0 → 4.6e18，@simd f64 踩过，
  修法 = arr_elem 类型表）。
- 全局 DCE 的三条保守规则不许放松：impl 家族全保留（vtable 全族）、@extern 前置
  fail-fast、("name") 叶子记引用（函数值/回调经裸名传递）。

### 文档权威分工（别再写串）

| 文档 | 管什么 |
|---|---|
| `CHANGELOG.md` | 版本特性、修复、回归项数的**历史记录** |
| `docs/STATUS.md` | **当前状态总表**（唯一"现在到哪了"口径） |
| `docs/GAPS.md` | 能力边界与缺口全表（§6.5.15 性能专项 / §6.5.16 库生态状态） |
| `docs/PERF.md` | **性能跑分权威**：全线数字、分配器解剖、实验记录（含回滚原因与重启前置） |
| `docs/LANG.md` | 语言特性精确语义与边界 |
| `docs/SRC.md` | src/ 三类资源布局（lib/ref/asset）与 read_asset |
| `docs/P0_LIBS.md` | P0 四件套 API 与实测 |
| `docs/SELFHOST.md` | 自举进度与阶段门禁 |
| `HANDOVER.md`（本文） | 快照、接力记忆、下一步排期 |

> 规则：任何"支持/不支持"的翻转，**同一次提交**里改 `STATUS.md` + `GAPS.md`，
> 再跑 `tools/dev/check_docs.py`。文档漂移按缺陷算。

### 下一步（按赢回幅度排序，不要跳）

1. **SHA-NI 64 轮序列**（65ms → ~3ms，20×）：基础设施全部就绪（cpuid 内建 +
   SHA 四指令族 + xmm 槽负数编码）。**前置**：Python mini-emulator 仿真 8 条 xmm
   指令语义，本机无硬件不能裸上——错误 hash 比慢更糟。方案在 GAPS §6.5.15。
2. **loop_sum 编译器三件套**（10.8 → ~4 c/iter，全程序通用）：
   phi copy 消除（寄存器分配 coalescing）+ do-while 变换（CFG 构建要容错
   jcc 回边——v1.17 实验记录在 PERF.md）+ cssub 形态。
3. **JSON → memchr 化 _skip_ws**（需 memchr/找字符内建）+ obj/arr 结构开销。
4. **IPv6**（AF_INET6 + sockaddr_in6 + 字面量解析——socket 家族改造，大活）。
5. **TCP 批量收发**便捷层 + 可靠 UDP（在 UDP 四件之上）。
6. **自举 parser 收敛**（bodydiff 一致 740/1383；剩余 top：impl 方法体、
   while 嵌套、astbody 的 option/result 对称支持）。
7. 命名空间/可见性、.qla 归档、LICM 根修（x64 布局敏感段错误）。

### 交接纪律

- 不要 `git reset --hard` / 不要删 `build/` 以外的任何目录；`archive/` 是旧快照。
- 跑完任何改动，至少复跑：`run_win_tests.py` + 三道门禁；动 parser 再加 bodydiff。
- **新增 IR 指令的检查表**见上一节"IR / 优化器纪律"——五处 + gen 双架构。
- 改 std 库的字符串/网络代码前，先读"写库须知"对应条目——五连修的坑全是环境性的，
  重犯成本很高。
- 推送：`git push` 直连时通时断；**稳定通道是 `python tools/dev/push_via_api.py`**
  （逐 blob 建 tree/commit 再 PATCH ref，凭据走 Windows Credential Manager）。
- 提交粒度：一个主题一个 commit，message 写清"根因 + 修法 + 验证"，不攒坨。

---

## 1. 语言特性状态（截至 v1.17）

✅ 已落地：真实整数宽度（u8..i32 边界截断）/ `let x: T` 标注 / `@simd`（int paddq +
f64 addpd 两路归约）/ `@no_preempt` / `rc[T]` / interface 动态分发（vtable 两字）/
atomic_add/cas/fence + spin_hint/now_cycle / std/sync / **用户泛型 fn f[T]**（单态化）/
const 编译期算术 / vec[vec[T]] / **str_alloc/str_from_mem/mem_ptr/mem_load32** /
**cpu_sha** / **udp_open/bind/sendto/recvfrom** / **wall_ms** / **read_asset** /
**sleep_ms / file_exists / file_size / fs_mkdir / fs_remove**

❌ 未做（有序）：闭包、FFI（自研后端）、defer、match 完整版（Phase 2，两侧同实现）、
用户泛型推断（现仅显式 `f[int](...)`）、AArch64 的 atomic/SHA-NI/vtable。

## 2. 标准库现状（v1.17g）

| 库 | 内容 | 状态 |
|---|---|---|
| std/core、std/mem | 基础 + arena/slab/**pool_***（指针式对象池）+ fdtab | ✅ |
| std/str | str_alloc/from_mem/mem_ptr 原语族 + split/join/find（批量构造） | ✅ |
| std/json | DOM 式解析（raw 池/buf/kids）+ builder | ✅ 41MB/s |
| std/gzip | DEFLATE + gzip（zlib 互操作 7/7）+ crc32 slice-by-4 | ✅ 26ms/1MiB |
| std/sha1、std/sha256(+HMAC)、std/aes（GCM）、std/b64、std/url、std/http、std/ws、std/sse | v1.6 面 | ✅ |
| std/net/core | TCP 槽位层（IOCP reactor） | ✅（批量收发 🟡） |
| **std/net/udp** | 内建四件 + parse_ip + loopback（t61 端到端） | ✅ v1.17c |
| **std/ds** | RingBuf + MinHeap | ✅ v1.17b |
| **std/serialize** | LEB128 varint + LE 定长 + 长度前缀帧 | ✅ v1.17b |
| **std/timer** | 轮询式定时器（after/cancel/poll，帧驱动零线程） | ✅ v1.17b |
| **std/rand / std/sort / std/log（+log_kv）/ std/time** | 五件套补齐 | ✅ v1.16/17g |
| gzip 解码（inflate）、TLS 握手、HTTP 客户端、DNS | — | ❌ GAPS §3.3 |

## 3. 编译器基础设施（v1.17d 后）

- **全局 DCE**：main 调用图不动点；impl 家族全保留；@extern fail-fast；
  `QLM_NO_DCE=1` 关闭、`QLM_DCE_VERBOSE=1` 打印统计。测试模式自动保留被测函数，
  普通构建自动剔除 test 块。
- **编译期死循环检测**：guard 变量不更新 + 常量上界 → 警告 + 函数名/循环序号；
  内联展开后的死循环同样命中。
- **bounds_elim 等值类**：str/vec 循环的 len 重复读取归等值类，窗口证明跨
  两次独立 len 读取生效——`while i < n { s[i] }` bounds 检查 4 条 jcc → 0。
- **qpm 包管理器**：`python tools/qpm.py install/add/remove/list`；依赖在项目
  `Quelmara.toml` 的 `[deps]`（path 或 git-url#rev）；lock.toml 锁 sha；
  编译器按主项目根 `.qpm/deps` 解析 import。
- **src/ 布局**：`[src] lib/ref/asset` 三条路径；库=目录即清单，import 按前缀惰性解析。

## 4. 怎么接着干

```bash
# Windows（本机可跑）
python tests/run_win_tests.py           # PE 回归（v1.17g 时点 124 项）
python tests/bodydiff.py                # 函数体对拍（一致 740 / 分叉 625）
python tests/lexdiff.py && python tests/parsediff.py
python tools/dev/check_docs.py          # 文档漂移门禁
python tools/dev/selfhost_status.py     # 自举进度（2/9）

# 基准（全部 min-of-N 已内置）
python tools/stage0/qlm_cli.py run bench/p0_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/gzip_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/json_bench.qma --target win
python tools/stage0/qlm_cli.py build examples/loop_sum.qma --target win -o build/loop_sum.exe

# 包管理 / src 布局端到端
python tools/qpm.py install             # 在有 [deps] 的项目里
python tools/stage0/qlm_cli.py build fixtures/srcproj/main.qma --target win

# 调试（capstone 在 envs/default venv）
QLM_DCE_VERBOSE=1 python tools/stage0/qlm_cli.py build x.qma --target win
QLM_NO_DCE=1 / QLM_NO_INLINE=1         # 隔离优化器
python tools/stage0/qlm_cli.py build x.qma --target win --dump-ir
```

## 5. 累计教训（按主题去重后的完整清单）

**正确性**：Result 的 Ok tag 按声明序查；`?` 边界报错不静默；worker 是寄存器分配
边界不内联；内联标签带 caller 名；C helper 只引用 helper 形参；`bin` 不能用
`sub dst, imm, dst` 模拟取反；泛型 `_prescan` 预登记 + `T{` 占位字面量。

**性能实验的两条铁律**（两次回滚换来的）：
- 单点核对全对 ≠ 装起来对——需要 capstone 反汇编对照或单元素 trace
  （@simd f64 就是反汇编发现 exe 里根本没有 movupd 才锁定的）。
- 优化前置条件不满足就回滚并登记重启条件（slice-by-4 等 mem_load32、
  do-while 等 CFG 容错）——错误代码比没有代码更糟。

**测试源码也是源**：m12 "死循环"从头到尾是测试自己漏了 `i += 1`——
先怀疑测试再怀疑编译器，但为此做的编译期死循环检测是真收获。

## 6. 版本控制 / 远端

- 仓库：`https://github.com/MonthZifang/Rosoto`，工作分支 `rename/quelmara`，
  远端 master 由 `tools/dev/push_via_api.py` 对齐（2026-10-22 = `68b8550`）。
- `github.com:443` 常被本机代理拦（CONNECT 502）；`api.github.com` 可达——
  push 直连失败就走 API 通道，**不要反复重试直连**。
- 凭据走 `git credential fill`（Windows Credential Manager，user.name=MonthZifang）。
- `.qpm/`、`build/`、`__pycache__` 已 gitignore；fixtures/srcproj 的本地产物勿提交。

### 目录改名（需要用户手动执行，仍待做）

```powershell
Rename-Item C:\Users\43551\Desktop\Rosoto Quelmara   # 外层目录
```

然后在改名后的目录重新打开项目；`.workbuddy/memory` 会随外层目录一起搬走。

### GitHub 仓库改名（需要用户手动执行，仍待做）

1. 打开 `https://github.com/MonthZifang/Rosoto/settings` → Repository name → 改为 `Quelmara` → Rename。
2. 本地更新 remote：`git remote set-url origin https://github.com/MonthZifang/Quelmara`，
   并同步 `tools/dev/push_via_api.py` 里的仓库名。
3. 旧地址自动 301，但建议同步更新文档里的 URL（`README.md` / `TUTORIAL.md`）。

## 7. 提交线（最近）

```
364bbba feat(v1.17g): 指针式对象池 pool_*（slab 封装）+ log_kv 结构化字段（t62）
a50a416 perf(v1.17f): gzip 59→26ms——追平 zlib + mem_load32 内建落地
c4d1898 perf(v1.17e): JSON 解析全面 raw 化——23 → 41 MB/s（1.8 倍）
871001e feat(v1.17d): 全局 DCE——main 调用图可达性
cf3dfe5 fix(v1.17c): UDP 全链路打通——五个连环根因修复
2d37fbf feat(v1.17b): std 库生态四件新库 + UDP 内建 + 生态状态表
8133c7b feat(v1.17): src/ 三类资源布局——库/引用/资源 + read_asset
1d4d5ea feat(v1.16b): @simd f64 归约修复落地 + 编译期死循环检测
41c0e0c feat(v1.16): std 五件套缺件——fs/sleep/rand/sort/log
4ac04ac feat(v1.15): SHA-NI 基础设施——cpuid 内建 + XMM/SHA 指令族
（更早见 CHANGELOG.md）
```
