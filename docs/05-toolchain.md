# 工具链与工程化

> 事实来源：`tools/stage0/qlm_cli.py`、`tools/qpm.py`、`Quelmara.toml`、
> `tools/dev/*`、`tests/*`、`.github/workflows/ci.yml`。

## 1. 命令行

入口两种，等价：

```bat
quelmara <cmd> [参数]                                  :: Windows 脚本
python tools/stage0/qlm_cli.py <cmd> [参数]            :: 任意平台
```

| 命令 | 作用 | 主要参数 |
|---|---|---|
| `build` | 编译（可一次给多个源） | `src...`、`--target`、`-o/--out`（单源）、`--no-opt`、`--dump-ir`、`-j`（多源并发）、`--no-cache` |
| `run` | 编译并运行 | `src`、`--target`、`--` 之后的参数传给程序 |
| `test` | 跑 `test "名字" { }` 块 | `paths`、`--target`、`--targets`（逗号分隔或 `all`）、`--no-opt`、`-j`（并发）、`--no-cache` |
| `fmt` | 格式化 | `paths`、`--check`（只检查）、`-q/--quiet` |
| `doc` | 文档生成（v1.92） | `paths`、`-o/--out`、`--format md\|json`、`--check`、`--missing` |
| `lex` | 词法分析 | `src`、`--stage0`（默认优先用自举词法器） |
| `bench` | 基准 + 回归对比 | `src`、`--runs`（默认 5）、`--baseline`、`--update-baseline`、`--threshold`（默认 10%）、`--targets` |
| `debug` | 源码级调试器（v1.75） | `src`（.qma 自动带调试信息构建）或产物、`--script`（命令脚本）、`--` 之后传给程序 |
| `cov` | 覆盖率：行 + 分支（v1.83） | `src`、`--hits`（命中日志）、`--min`（行阈值，默认 80）、`--min-branch`（分支阈值，默认 0=不设）、`--append`（累加多次运行）、`--lines-only`、`--` 之后传给程序 |
| `fuzz` | 编译器前端模糊测试（v1.83） | `src`（种子）、`--cases`（默认 64）、`--seed`（默认 1）、`--out`、`--timeout-ms`、`--max-seconds`、`--emit`（连后端一起跑） |
| `lsp` | 语言服务器（v1.91） | `--stdio`、`--root`、`--index FILE`、`--symbols FILE`、`--at FILE:L:C`、`--completions FILE:L:C`、`--check FILE` |
| `cache` | 增量编译缓存（v1.100） | `--stat`（默认）、`--clear`、`--prune DAYS` |
| `version` | 版本与能力 | — |

`--target` 取值：`native`（ELF64）/ `win`（PE32+）/ `arm64`（AArch64 ELF）/ `c`（C99，仅交叉验证）。

`build` / `run` 支持 `--dbg-info`：随 PE 发射 `.qlmdbg` 调试节（行表 + 变量位置表 + 结构体布局）。**只支持 `--target win`**；不带该开关的默认构建代码生成路径与开启前完全一致（标记指令根本不进 IR；改动全是新增指令分支）。

```bash
python tools/stage0/qlm_cli.py run examples/hello.qma --target win
python tools/stage0/qlm_cli.py test tests/selftest.qma --targets all
python tools/stage0/qlm_cli.py build examples/loop_sum.qma --target win -o build/ls.exe
python tools/stage0/qlm_cli.py bench bench/p0_bench.qma --runs 5
```

### 1.1 源码级调试器（v1.75 / v1.80）

自研链路：编译器把语句行号与变量位置随 PE 写进 `.qlmdbg` 节（自研 JSON 格式），
`qlm_dbg.py` 用 Windows 调试 API 做源码断点 / 单步 / 变量查看 / 调用栈。
零外部依赖（无 gdb / capstone / WinDbg / SDK）。同一份调试表还会编码一份
**标准 DWARF v4**（v1.80），供外部工具消费。

```bash
python tools/stage0/qlm_cli.py debug fixtures/dbgdemo/main.qma        # 构建+调试
python tools/stage0/qlm_cli.py debug build/x.qex                      # 直接调试产物
python tools/stage0/qlm_dbg.py build/x.qex --script cmds.txt          # 无人值守（测试用）
```

会话命令（`--script` 每行一条，`#` 注释；交互时同样输入）：

| 命令 | 作用 |
|---|---|
| `break 文件:行` / `break 函数名` | 下断点（源码行取该行第一个语句边界；函数名取入口） |
| `run` / `continue` / `c` | 继续到下一个断点或退出 |
| `step` / `s` | 单步进入（行粒度，进行函数同样停） |
| `next` / `n` | 单步跨过（被调函数用返回地址临时断点跳过，不逐指令爬） |
| `finish` / `f` | 运行到当前函数返回（返回地址临时断点） |
| `print 表达式` / `p` | 变量求值：`x`、`p.x`、`p.sub.y`（int/bool/f64/str/struct） |
| `locals` | 当前帧全部存活变量 |
| `bt` | 调用栈（RBP 帧链，修正了序言多压 callee-saved 的偏移） |
| `list [行]` | 看当前行附近源码 |
| `info break` / `delete N` | 断点列表 / 删除 |
| `quit` / `q` | 结束（杀掉被调试进程） |

```
[dbg] breakpoint 1: main.qma:35 -> rva 0x11a1
[dbg] stopped: fixtures/dbgdemo/main.qma:35 in main()
[dbg]   35|     let r = work(x, y)
[dbg] print p.x
[dbg] p.x = 7 (0x7)
[dbg] bt
[dbg] bt #0 main() fixtures/dbgdemo/main.qma:35
[dbg] bt #1 <entry>() <library>
```

**两种调试信息，一份数据源**（`--dbg-info` 时同时发出）：

| 节 | 格式 | 谁用 |
|---|---|---|
| `.qlmdbg` | 自研 JSON：行表 + 变量位置表（含活跃区间 `bind`/`last`）+ 结构体布局 | `qlm_dbg.py`（要活跃区间，判"已超出生命周期"） |
| `.debug_abbrev` / `.debug_info` / `.debug_line` / `.debug_loc` | **标准 DWARF v4** | 外部工具（llvm-dwarfdump / objdump / IDE） |

DWARF 三条口径（细节见 `tools/stage0/qlm_dwarf.py` 模块头）：

1. **地址是 RVA（镜像相对）**：PE 调试节不参与基址重定位，写绝对地址就得给
   调试节造重定位表；RVA 与调试器的 `PC - image_base` 同口径。
2. **帧基址是 RBP**（`DW_AT_frame_base = DW_OP_breg6 0`），栈槽写
   `DW_OP_fbreg -off`，与 codegen 的 `[rbp-off]` 同源。
3. **寄存器号要翻译**：内部编号是 Rax/Rcx/Rdx/… 的声明顺序，DWARF x86-64 是
   rax/rdx/rcx/rbx/rsi/rdi/rbp/rsp/…——照抄会读到错的寄存器。

自研边界（做不到的写在这里，不粉饰）：

- **只支持 Windows PE**：`--dbg-info` 对 `native`/`arm64`/`c` 目标 fail-fast
  （ELF 后端不发射调试节，ptrace 前端未做）。
- **不发 PDB**：Windows 原生链路要 MSF 容器 + CodeView 记录，与 DWARF 是两套；
  本机没有 MSVC 工具链可验证，宁可不做。DWARF 侧已经可用。
- **库函数帧无行号**：import 的文件行号属于别的文件，显示 `<library>`。
- **调试构建默认不内联**（v1.80）：内联后被调函数变成死代码，`break 文件:行`
  静默不命中、`bt` 看不到那一帧。调试构建以断点语义优先（`QLM_NO_INLINE=1`
  仍可显式关）。因此"内联帧"不再是需要解释的现象。
- **`print` 限变量与 `a.b.c` 字段路径**：数组下标、算术表达式未做。
- **变量可见区间 = 最后一次使用之前**：之后寄存器/帧槽可能被复用，报
  "已超出生命周期"而不显示过期值（宁缺勿错）。
- **入口停点上下文不完整**：初始断点处内核返回的整数上下文缺 Rip，
  `step`/`print`/`bt` 要求先 `run` 到真实断点。
- 带 `--dbg-info` 的构建，调度/循环展开决策会变（标记计入指令数）——
  与 `gcc -g` 同理；默认构建不受影响（标记不进 IR，代码生成路径与开启前一致）。

性能口径见 `06-status.md` §3.8（构建开销、产物体积占比、每命中/每步延迟）；
复现脚本 `python tools/dev/dbg_bench.py`。

### 1.2 文档生成（v1.92）

`///` 的语法在语言层（`02-language.md` §2.4），`quelmara doc` 是它的唯一消费方：
扫源码里的 doc comment，渲染成 Markdown 或 JSON。**不依赖编译器**（纯文本扫描），
所以对任意 .qma 目录都能跑，不需要能编译通过。

```bash
python tools/stage0/qlm_cli.py doc std/                       # Markdown -> stdout
python tools/stage0/qlm_cli.py doc std/ -o docs/api.md         # 写文件
python tools/stage0/qlm_cli.py doc std/ -o docs/api.md --check # 只校验一致（退出码 1 = 漂移）
python tools/stage0/qlm_cli.py doc std/ --missing              # 公开声明缺文档 -> 退出码 1
python tools/stage0/qlm_cli.py doc std/ --format json          # 机器可读（LSP 预留）
```

输出形态：`# 标题` → 每模块一个 `## \`路径\``（下面接 `//!` 模块文档）→ 每个公开声明一个
`### \`名字\`` + 文档段落 + ```` ```quelmara ```` 代码块。fn 只出签名（截到行内第一个顶层 `{`），
struct/enum/interface 出**整个声明块**（含字段与字段行内注释）。

两个门禁模式：

| 模式 | 判什么 | 退出码 |
|---|---|---|
| `--missing` | 顶层 `pub` 声明有没有 `///`；有没有"脱离"的 doc 块（写了没挂上） | 有问题 1 |
| `--check` | `-o` 指的文件与源码 doc comment 是否一致（文档漂移） | 不一致 1 |

自研边界（做不到的写在这里）：

- **只收顶层声明**：`impl` 内的方法文档没有做（缩进的 `///` 按普通注释处理）。
- **不做交叉引用/链接检查**：`[foo]` 之类就是普通文本，不解析、不校验目标存在。
- **不渲染 Markdown**：文档正文原样透出，标题层级由工具给，正文里的 `#` 不做处理。
- **不做增量**：每次全量扫（全库耗时见 `06-status.md` §3.9）。

仓库自身的 `docs/03-stdlib.md` 不是 `quelmara doc` 直接生成的：它由
`tools/dev/gen_stdlib_doc.py` 生成（模块顺序与一句话简介需要人工登记），
但**扫描与解析走同一份实现**（`tools/stage0/qlm_doc.py`），不会出现两套口径。
`--require-doc` 是它的覆盖门禁，与 `doc --missing` 同源。

### 1.3 覆盖率：行 + 分支（v1.83，汇总工具用 Quelmara 写）

```bash
python tools/stage0/qlm_cli.py cov fixtures/dbgdemo/cov.qma
python tools/stage0/qlm_cli.py cov src/main.qma --min 85 --min-branch 60 --hits build/cov.tsv
python tools/stage0/qlm_cli.py cov src/main.qma --hits build/cov.tsv --append -- 20   # 累加第二次运行
```

三段分工，**统计与报告那段是自研语言写的**（`tools/qlm_cov.qma`）：

| 段 | 做什么 | 用什么 |
|---|---|---|
| 采集 | 源码行入口 + 条件跳转各下一个断点，跑到退出，写命中日志 | `qlm_dbg.py --cov`（必须走 Windows 调试 API） |
| 汇总 | 读 PE 节表 → 读 `.qlmdbg`（JSON）→ 对命中日志 → 行/分支/函数/文件四级统计 | **`tools/qlm_cov.qma`**（Quelmara） |
| 门禁 | 行低于 `--min`、或分支低于 `--min-branch` 时退出码 1 | 同上 |

为什么汇总工具要用 Quelmara 写：它同时吃**二进制**（PE 节表）和 **JSON**
（`.qlmdbg`），是"自研语言能不能干工具链的活"的直接检验；跑通之后，
工具链里"只读分析"类工具（依赖图、符号表、覆盖率、体积分析）都可以照这个形状写。
v1.83 又加了 `tools/qlm_fuzz.qma`（变异器），同一形状的第二个工具。

报告长这样（`fixtures/dbgdemo/cov.qma`，只走 `if` 的 else 支）：

```
qlm_cov — 覆盖率报告（Quelmara 工具链）
  文件: fixtures/dbgdemo/cov.qma
  行:   4/5 (80.0%)
  分支: 1/2 (50.0%)
  未覆盖行: 9
  未覆盖分支: 8->9
  函数:
    pick        行 2/3 (66.7%)  分支 1/2 (50.0%)
    main        行 2/2 (100.0%)  分支 0/0 (—)
  结果: 达标（行阈值 80%，分支阈值 0%）
```

**行口径**（避免"100% 覆盖"的假象）：

- 分母 = `.qlmdbg` 行表里出现的**唯一行号**——空行、注释行、纯声明行不在表里，
  所以不会因为"没写代码的行"拉低覆盖率，也不会因为把语句写在一行里虚高。
- 分子 = 该行任一指令入口被命中过（同一行多个入口只算一次）。
- 只统计主文件：`.qlmdbg` 本来也只收主文件，库函数行号属于别的文件。

**分支口径**（v1.83）：

- 分母 = 每条条件跳转的**两条边**（跳 / 不跳），共 2 × 分支数。
  所以 `if` 只走一条支时分支覆盖率必然 ≤ 50%，不会再出现"行 100% 就以为覆盖完整"。
- 边 = `(分支指令 rva, 去向 rva)`；不跳边的去向恒为 `分支 rva + 6`（本编码器的
  `jcc` 一律 rel32）。
- **判定不单步**：断点打在 `jcc` 首字节上，命中时 EFLAGS 还是上一条指令留下的
  那份（`int3` 不改标志位），按条件码直接算出"跳没跳"。比"命中后再单步一条看
  RIP"便宜一半事件（每边 1 个事件 vs 2 个）。
- **只收源码级分支**：跳转目标必须是语句入口（行表里的某个偏移）。不是的话这条
  `jcc` 是编译器生成的机械跳转——`assert` 失败块、定长数组越界检查的 panic 块、
  `args()` 展开的拷贝循环、`@simd` 的内联循环——算进分母只会把"分支覆盖率"变成
  编译器体检报告。实测 `tests/t64_math.qma` 的 49 条 `jcc` 里 41 条是源码分支，
  剩下 8 条全是 `assert` 失败块；`tools/qlm_cov.qma`（440 行、map/vec/字符串密集）
  过滤后只剩 39 条——工具代码越重，机械跳转越多。
- 条件级：`if a > 0 && b > 0` 的两个子条件各自是一条 jcc、各自两条边，所以
  **短路子条件单独计数**（这是分支覆盖的自然结果，不是另做一套 MC/DC）。
- `while` 的两条边 = "再进循环体" / "退出循环"，与 `if` 同口径。
- **`assert(cond)` 也算一条分支**：成立边是正常路径（总被走），不成立边是中止块
  （几乎永远不走）。所以 assert 密集的文件分支覆盖率会停在 50% 附近——这与 gcov /
  llvm-cov 的口径一致，不是缺陷；`tests/t64_math.qma`（40 个 assert）实测就是
  41/82 = 50%。要门禁时按文件分级设 `--min-branch`，别用同一个阈值卡测试文件。

**增量合并**（v1.83）：`--append` 把本次命中**累加**进 `--hits` 已有日志（同一
`rva`/边按次数求和），用于"多组输入 / 多次运行拼出一份覆盖率"。不加 `--append`
就是覆盖写。合并结果由 `qlm_cov.qma` 的 `--merge-out` 落盘，格式仍是纯文本：

```
# qlm_cov hits v2（qlm_dbg --cov 产出）
L <rva> <hits>                       行入口命中
E <branch_rva> <target_rva> <hits>   分支边命中
```

v1.82 的旧格式（`rva<TAB>hits`）仍然接受，历史日志可以继续合并。

`--lines-only` 不下分支断点（采集快一截），此时报告分支为 `0/0 (—)`——
"没有可覆盖对象"和"覆盖率为 0"必须能分开读。

### 1.4 模糊测试（v1.83，变异器用 Quelmara 写）

```bash
python tools/stage0/qlm_cli.py fuzz fixtures/dbgdemo/cov.qma --cases 64 --seed 1
python tools/stage0/qlm_cli.py fuzz std/json.qma --cases 40 --seed 21 --emit
```

| 段 | 做什么 | 用什么 |
|---|---|---|
| 造用例 | 读种子源码 → 1–4 处变异 → 写 `case_NNNN.qma` | **`tools/qlm_fuzz.qma`**（Quelmara 写） |
| 判定 | 逐个编译，分类 built / rejected / deep / bug / slow | `tools/stage0/qlm_fuzz.py`（进程内跑前端） |
| 报告 | 计数 + 崩溃详情 + 复现命令 | 同上 |

为什么判定在 Python、变异在 Quelmara：前端（lex/parse/lower/opt）是 stage-0
Python 模块，进程内调用 10–350 ms/例（看种子大小），起子进程光解释器启动就要
0.4 s；而变异是纯字符串变换，正好用自研语言写。同 seed 必得同一批用例（Lehmer LCG），
失败可复现。

判定口径（**`SyntaxError` 是设计好的 fail-fast，不是缺陷**）：

| 结果 | 含义 | 计入失败 |
|---|---|---|
| `built` | 前端接受了这个变异体（语义可能错，但编译器没崩） | 否 |
| `rejected` | 抛 `SyntaxError`——设计好的诊断 | 否 |
| `deep` | `RecursionError`：嵌套过深撞 Python 递归上限（单独计数） | 否 |
| `bug` | 其它异常（`IndexError`/`KeyError`/`TypeError`/…） | **是**（退出码 1） |
| `slow` | 单例超过 `--timeout-ms`（只报告） | 否 |

只变异 ASCII 字节：删/插一个 ASCII 字节不会切断多字节 UTF-8 字符，用例因此
始终是合法 UTF-8。不这么限的话，中文注释被切一半会让每例都变成
`UnicodeDecodeError`，把真信号全淹掉（实测 16 例里 11 例如此）。

边界：

- **默认只跑前端**（lex/parse/lower/opt）。`--emit` 才连 x64 后端一起跑，
  慢 3–5 倍，能抓到发射层缺陷。
- **单例死循环无法在进程内中断**（Python 无线程级 kill）：用 `--max-seconds`
  限总时长，测试侧用 `subprocess` 超时兜底。
- **非 UTF-8 源文件**目前会让编译器抛 `UnicodeDecodeError`（Python 回溯）而不是
  干净诊断——fuzz 分类器会把它算 `bug`，变异器主动避开这类输入。见
  [`07-gaps.md`](07-gaps.md) §7.11。
- 不是覆盖率引导的（没有 AFL 那套 feedback loop）：变异是无向的，靠用例数量
  堆概率。

### 1.5 性能回归门禁（v1.88）

`quelmara bench` 量的是**进程墙钟**（含冷启动），只能看出"慢了半秒"这种量级；
性能门禁用另一套夹具，量**进程内 `now_ns`**，并且按同一进程里的校准形状归一化。

```bash
python tools/dev/bench_gate.py --check              # 对本机基线判定（默认动作）
python tools/dev/bench_gate.py --update             # 代码/机器变了才重建基线
python tools/dev/bench_gate.py --ab origin/master   # 与修订做同机 A/B（CI 用）
```

三段：

| 段 | 是什么 | 在哪 |
|---|---|---|
| 夹具 | 6 个固定形状 + 1 个校准形状，输出机器可读行 | `bench/gate_bench.qma`（**Quelmara 写**） |
| 判定 | 解析 → 归一化 → 比基线 / 比另一棵树 → 退出码 | `tools/dev/bench_gate.py` |
| 自测 | 门禁自己也要被门禁：伪造回归必须判失败 | `tests/bench_gate_test.py` |

输出协议（改协议要同时改两边）：

```
QLMBENCH|<形状>|<迭代数>|<总纳秒>     # arith / branch / memscan / strbuild / mapstr / sha256
QLMCAL|<迭代数>|<总纳秒>              # 校准形状：纯标量整数依赖链
QLMDIGEST|<十进制校验和>              # 所有形状结果折成一个数
```

三条设计决定，都是被噪声逼出来的：

1. **归一化（`QLMCAL`）**：绝对纳秒换机器就不可比。同一进程里跑一段固定的
   标量整数链做分母，得到"这个形状相当于多少次校准迭代"——主频差异被约掉，
   剩下的是代码生成质量的差异。它约不掉核数/缓存/内存带宽，所以基线 key 里
   **带 CPU 型号**：换了机器只 SKIP，不误判。
2. **校验和优先（`QLMDIGEST`）**：性能门禁最怕"变快了，因为算错了"。
   校验和与基线不一致 → 直接失败，不看时间。
3. **噪声闸（回归必须大于噪声）**：每个形状先算自己的离散度（`max-min/min`），
   本次差值没超过这个离散度就只标 `noisy`、不判失败；离散度超过 `--noise-cap`
   时同样只报数。把噪声当回归，会训练出"看到红就重跑"的习惯——那等于没有门禁。
   这一条是实测逼出来的：同一份代码在本机不同时刻能差 ±30%（另一条轨在并行构建）。

两种判定模式：

| 模式 | 比什么 | 用在哪 | 默认阈值 |
|---|---|---|---|
| 基线（`--check`） | 本机数值 vs `bench/perf_baseline.json` 里同 key 的记录 | 开发机、参考机 | 25% |
| A/B（`--ab REV`） | 工作区 vs 某个 git 修订，**同机、交错执行** | CI（PR 与 base 分支比） | 15% |

- 基线模式阈值放宽，是因为"跨时间点"的对比会带上机器状态漂移（VBS/负载），
  实测漂移量见 `06-status.md` §3.9；A/B 是同一次运行内交替跑两边，可以收紧。
- **交错执行**：`--ab` 不是"先跑完 A 再跑完 B"，而是 A/B/A/B…，两边各自取最小。
  否则后跑的一边会把整段漂移算到自己头上（实测同一份代码能漂 ±10%，方向随负载变化）。
- 语义变了（校验和不同）时 A/B **不做性能判定**，直接 SKIP：语义改动归主回归验。

硬失败项（与时间无关）：校验和不一致、产物体积增长超 `--size-threshold`（默认 10%）。

灵敏度自检：`tests/bench_gate_test.py` 会把基线改成"快一倍"，断言门禁判 FAIL
且退出码 1；再分别把校验和与体积改坏，断言这两项也能拦住。**不靠"造一个慢版本"
来演示**——那种演示只能证明它慢，证明不了门禁抓得到。

```bash
python tools/dev/bench_gate.py --check --no-opt   # 关优化构建，用来看"优化值多少"
```

`--no-opt` 只是把构建开关透传下来（二分定位优化器改动时用）。本机实测这几个
形状对优化几乎不敏感，别拿它当"优化没生效"的证据；口径见 `06-status.md` §3.9。

### 1.6 语言服务器（v1.91）

`quelmara lsp` 起一个 LSP 3.17 子集的服务器（stdio JSON-RPC，**纯标准库**），
数据源是 `tools/stage0/qlm_index.py` 的语义索引。

```bash
python tools/stage0/qlm_cli.py lsp                        # 起服务（编辑器 stdio 连接）
python tools/stage0/qlm_cli.py lsp --index src/main.qma    # 只索引并打印统计（性能口径）
python tools/stage0/qlm_cli.py lsp --check src/main.qma    # 打印诊断，有 error 退出码 1
python tools/stage0/qlm_cli.py lsp --at src/main.qma:63:14           # 该位置解析成什么
python tools/stage0/qlm_cli.py lsp --completions src/main.qma:63:16  # 该位置补全什么
```

| 能力 | 触发 | 给什么 |
|---|---|---|
| 补全 | `textDocument/completion` | 作用域内局部（含形参）→ 本文件顶层 → 导入的 `pub` → 内建函数 → 关键字；`.` 之后按接收者类型给字段/方法/变体 |
| 跳转 | `textDocument/definition` | 本文件声明，或 import 进来的 `pub` 声明（跨文件） |
| 引用 | `textDocument/references` | 本文件精确；顶层符号按需索引整个工作区 |
| 重命名 | `prepareRename` / `rename` | 与引用同范围；关键字/非法标识符/内建直接拒绝（`-32602` 并带原因，不是静默 null） |
| 悬停 | `textDocument/hover` | 签名 + 种类 + 声明上方 `//` 注释 + `文件:行` |
| 大纲 | `textDocument/documentSymbol` | 顶层声明 + 成员（字段/变体/方法）树 |
| 高亮 | `textDocument/documentHighlight` | 同符号在本文档内的出现（声明/引用区分） |
| 全局符号 | `workspace/symbol` | 全工作区名字子串查（首次调用建全量索引） |
| 诊断 | `publishDiagnostics` | 非法字符 / 未闭合字符串 / 括号不配对 / 顶层重名 |

**为什么索引不建在编译器前端上**（这是本模块最重要的一个决定）：

`qlm.Parser` 要求语法完整——一个字符打错就抛 `SyntaxError`，整篇符号全部消失。
编辑器里正在编辑的文件**永远**是半成品（光标停在 `fn foo(` 上时也要补全）。
所以 `qlm_index` 只做**词法 + 结构**（括号配对、声明关键字），不做语义检查：
它能读当前 `qlm.Parser` 读不了的文件——`std/timer.qma` 用了顶层 `let`、
`std/http.qma` 拿 `rc` 当变量名，两者都过不了前端，但索引照常给出完整符号表
（`tests/lsp_test.py` 的 `[B]` 段钉住这一点）。

**为什么另写一份词法**：`qlm.tokenize` 的 `Tok` 只有 `kind/val/line`，没有列号，
而 LSP 的每个请求/响应都以 (行, 列) 定位。另写一份必然漂移，所以 `qlm_index.scan`
与 `qlm.tokenize` **逐条同构**（同 `KEYWORDS`/`SYMBOLS`、同数字与字符串转义、
同 `\xNN` 单字节语义），只是多记 `off`/`end`；`tests/lsp_test.py` 用**全仓库
`.qma` 对拍**（kind + val 逐记号相等）钉住二者一致——词法一改，测试立刻红。

边界（做不到的写在这里）：

- **诊断只到词法/结构层**：类型错误、未定义函数不报——那需要完整前端，
  而完整前端在编辑器场景不可用（理由见上）。
- **索引不带类型系统**：`.` 之后的成员靠语法推断（形参标注 / `let` 标注 /
  结构体字面量 / 枚举构造 / `fn()` 返回类型 / 类型参数约束里的接口方法）；
  推不出来就是"未解析"，补全退化为本文件成员，**不猜**。
- **`didChange` 整篇重建**：没有增量索引。单文件耗时见 `06-status.md` §3.10，
  1.7k 行的文件约 100 ms，再大要靠客户端 debounce 或后续做增量。
- **重命名只改解析得到的引用**：接收者类型未知的 `.field` 只有在"该字段名在
  本文件唯一"时才一并改；跨文件重命名会先按需索引工作区（首次较慢）。
- **不发 PDB、不做语义高亮与格式化**：`fmt` 是独立命令；语义高亮需要客户端
  主题映射，未做。

编辑器接入：任何 LSP 客户端都能驱动（`documentSelector` 用
`{ language: "quelmara" }`，`command` 填 `python <repo>/tools/stage0/qlm_cli.py lsp`）。
仓库**不附** VS Code 插件——只保证协议这一侧可被驱动，`tests/lsp_test.py`
就是一个自写的最小客户端（38 条断言，含真 JSON-RPC 往返）。

### 1.7 增量与并行编译（v1.100）

编译器是**整程序编译**：主文件 + import 闭包一次解析、单态化、降级、优化、编码。
没有目标文件格式（`.qla` 仍是 🚧），所以"改一行只重编一个函数"做不到；
但"什么都没改还全量重编"是纯浪费。两个开关分别对付这两件事：

| 开关 | 默认 | 作用 |
|---|---|---|
| 编译缓存 | **开** | 单元内容没变就不编，直接取上次的产物 |
| `--no-cache` / `QLM_NO_CACHE=1` | — | 强制重编（不读也不写） |
| `build -j N` | 核数（上限 8） | **多源**构建时并发编 N 个单元 |
| `test -j N` | 核数（上限 8） | 并发跑 N 个文件的构建+执行 |

```bash
python tools/stage0/qlm_cli.py build examples/hello.qma --target win
#   [qlm] ... | 重编 1352 ms（无条目）
#   [qlm] ... | 缓存命中 141 ms
python tools/stage0/qlm_cli.py build examples/*.qma --target win -j 8   # 多源并行
python tools/stage0/qlm_cli.py test tests -j 8                          # 并行回归
python tools/stage0/qlm_cli.py cache --stat                             # 条目/体积/命中率
python tools/stage0/qlm_cli.py cache --clear                            # 清空
python tools/stage0/qlm_cli.py cache --prune 7                           # 删 7 天没用的
```

#### 缓存键（`tools/stage0/qlm_cache.py`）

一个"编译单元" = 一个主文件 + 它的 import 闭包。键是下面六项的 sha256：

| 项 | 为什么在键里 |
|---|---|
| `schema` | 缓存格式版本，改格式即全废 |
| **编译器指纹** | `tools/stage0/*.py` 全部内容的哈希。**任何一个字节变了，全部条目失效**——这是"缓存不会掩盖编译器回归"的唯一保证，不许为省几毫秒换成 mtime |
| `target` / 优化 / 调试开关 | 不同产物 |
| 主文件内容 | 内容寻址，不看时间戳 |
| **源根目录清单** | `std/`、`[src].lib`、`[src].ref` 下 `.qma` 的名字+大小。import 解析是"取第一个存在的候选"，新增同名文件会**改变解析结果却不改变任何已存在文件**，只有清单能堵住 |
| `QLM_*` 环境快照 | 这些开关会改代码生成（DCE/内联/LICM/跳 pass）。全量纳入，漏一个就会产出"看着命中、其实编错"的条目 |

命中还要过两道校验：**闭包里每个文件的内容**与记录一致（逐文件 sha256）、
**产物 sha256** 与记录一致（防半截写/外部损坏）。任何一条不满足就重编，
并把原因打出来（`重编 1870 ms（依赖已改 std/str.qma）`）——命中要能解释，
不命中也要能解释。

#### 闭包怎么来的（不重新实现 import 解析）

编译期间挂一个 `sys.addaudithook`，把编译器**真正 open 过**的文件记下来。
闭包的定义就是"编译器读过的文件"，不是近似——`Quelmara.toml`、
`read_asset` 嵌进去的资源都会自然进闭包。记不到任何文件就不写缓存
（**宁可不缓存，也不缓存一个闭包不完整的条目**）。

刻意不复用 `qlm.load_program` 的解析顺序去推闭包：那是两份会漂的逻辑。
这里用的是"观测"，解析规则怎么改都不影响正确性；改了也没关系——
编译器指纹一变，旧条目本来就全废。

#### 并行：粒度是单元，不是函数

`-j` 把 N 个单元分给 M 个进程（`ProcessPoolExecutor`，spawn）。每单元一个
独立进程 → 不共享 GIL、不共享编译器状态；输出仍按输入顺序打印，
所以**并行不改变结果**（`tests/cache_test.py` 第 9 段钉住串行/并行输出逐行相同）。

并行收益有天花板，本机实测的瓶颈是**进程创建**（见 `06-status.md` §3.14）：
VBS 开启时一个空 Python 进程要 1.3 s，8 个 worker 的启动成本就把轻单元的
收益吃掉了。所以：

- 单元越重、越多，并行越接近线性；单元很轻时，**串行 + 缓存**通常更快。
- `build` 的串行路径在**同一进程内**编所有单元（import 只付一次），
  并行路径每个 worker 各付一次——这是"最优串行 vs 最优并行"的比较。

#### 边界（做不到的写在这里）

- **不是目标文件格式**：没有 `.qla`，所以没有函数级增量、没有"只重编变了的
  模块再链接"。这里省掉的是**整个单元**的编译，跨单元复用不做。
- **单文件内部不并行**：并行粒度是单元。一个 30 万行的文件仍然单进程串行。
- **不跨机器共享**：缓存里是产物二进制，绑 target + 编译器指纹；
  换机器/换 Python 版本后条目仍可能命中（产物是原生码，与 Python 无关），
  但**编译器的哈希必须一致**，所以共享缓存目录只在同一份 `tools/stage0` 下有意义。
- **目录清单变化会让全部条目失效**：这是上面第 5 条故意的（安全换速度）。
- 缓存目录是项目根下的 `.qlmcache/`（`QLM_CACHE_DIR` 可改），已在 `.gitignore`；
  删掉它只损失一次重编，不影响任何产物。

回归：`tests/cache_test.py`（24 条：冷/热、改主文件、改依赖、改回原样命中旧条目、
开关隔离、`--no-cache`、产物截断、`--stat/--clear`、串行=并行）。
性能：`tools/dev/incr_bench.py`，数字见 `06-status.md` §3.14。

## 2. 配置文件 `Quelmara.toml`

从源文件目录向上查找（以及 cwd），**最近的一份生效**；缺失则用默认值。
旧配置名会直接报错并给出 `git mv` 提示。

```toml
[core]
multicore = true      # false = 显式单核
threads   = 0         # 0 = 物理核数
affinity  = "none"    # none | compact | scatter | [0,1,2]
preempt   = true

[src]                 # 三类资源根（见 §3）
lib   = "src/lib"
ref   = "src/ref"
asset = "src/asset"

[net]
backend      = "auto"    # auto | io_uring | epoll | kqueue | iocp
io_threads   = 0
max_conns    = 1000000
recv_buffer  = 4096
send_buffer  = 4096
tcp_nodelay  = true
reuse_port   = true
backpressure = "drop"    # drop | close | block

[memory]
arena_default = false
heap_limit_mb = 512

[build]
opt          = "speed"
lto          = true
target       = "native"
bounds_check = true      # false = 去掉定长数组越界检查（更快，越界即 UB）
```

默认值定义在 `tools/stage0/qlm.py:33` `DEFAULT_CONFIG`。

## 3. `src/` 三类资源

项目可在 `Quelmara.toml` 的 `[src]` 段声明三条根路径，编译器**按名称/前缀惰性解析**：

| 类别 | 默认路径 | 用途 | 引用方式 |
|---|---|---|---|
| 库 `lib` | `src/lib` | 可 import 的模块，**目录即库** | `import ws.ws_core` → `src/lib/ws/ws_core.qma` |
| 引用 `ref` | `src/ref` | 跨项目引用锚点 | 同 import；`.qpm/deps` 优先于它 |
| 资源 `asset` | `src/asset` | 运行期读取的静态资源 | `read_asset("greeting.txt")` |

`import` 查找顺序：**主文件目录 → `std/` → `[src].lib` → `[src].ref` → `.qpm/deps`**。

`read_asset(name)` 在**编译期**把资源内容嵌入为全局字符串，运行期按名索引——
不需要打包外部文件。端到端夹具：`fixtures/srcproj`。

## 4. 包管理 qpm

```bash
python tools/qpm.py install [--offline] [--locked] [--refresh] [--registry NAME]
python tools/qpm.py add <name> <spec>       # 写 [deps] 后立即 install
python tools/qpm.py remove <name>
python tools/qpm.py list | tree | verify
python tools/qpm.py update [name]           # 忽略锁重新解析
python tools/qpm.py publish [--registry NAME] [--dry-run]
python tools/qpm.py yank <name> <version> [--registry NAME]
python tools/qpm.py registry add <name> <url|目录> | remove <name> | list
```

一句话：`[deps]` → **一张扁平依赖图** → `<project>/.qpm/deps/<name>/`；
编译器按 `import a.b` 直接找到 `.qpm/deps/a/b.qma`（`tools/stage0/qlm.py::_qpm_candidates`）。
没有符号链接（Windows 上不可靠），也没有嵌套 node_modules 式的目录树。

### 4.1 三种依赖来源

| 来源 | spec 形态 | 解析方式 |
|---|---|---|
| 路径 | `path:../mylib`、`./x`、`../x`、`/abs`、`C://x` | 相对**声明它的那个包**解析成绝对路径，整目录复制（跳过 `.git`/`build`/产物） |
| git | `git:https://…#v1.2.3`、`https://…#^1.2.0`、`git@host:u/r#rev` | `#` 后是精确 rev 或 semver 区间；区间先 `ls-remote --tags` 选 tag |
| registry | `^1.2.0`、`1.2.3`、`*`（包名 = `[deps]` 的 key） | 查索引 → 选满足**全部**约束的最大版本 → 下 `.qpk` |

来源判定是**语法式**的（v1.45 口径，未改）：`path:` / 相对路径 / 盘符 → 路径；
`git:` / 裸 URL（`http(s)://`、`file://`、`ssh://`、`git@`）→ git；其余一律
registry。名字恰好长得像区间的 tag 会被当区间解析，失败即报错。

区间语义（`tools/qpm_semver.py`，纯标准库）：`^ ~ > >= < <= = *`、通配段
（`1.2.x` / `1.*`）、逗号/空格 = AND、`||` = OR；预发布版本默认不选中，
要它必须显式写进区间。区间语法与边界见该模块 docstring。

### 4.2 registry 协议（自研，v1.99）

一个 registry 就是一棵目录树，`<base>` 可以是本地目录（`path:`/`./`/`C://`）
或 `http(s)://`：

```
<base>/index/<name>.json
    {"name": "alpha",
     "versions": {"1.2.0": {"deps": {"beta": "^1.0"},
                            "sha256": "<.qpk 的 sha256>",
                            "size": 1234,
                            "yanked": false}}}
<base>/packages/<name>-<version>.qpk      # 确定性 tar.gz
```

- **索引是"每包一个 JSON"**（sparse index 形状）：解析阶段只读索引，不下载包体
  ——`deps` 字段就在索引里，所以"解析 40 个包"和"下载 40 个包"是两件事。
- **包体是确定性 tar.gz**：成员按相对路径排序、`mtime=0`、`uid/gid=0`、
  gzip 不带文件名与时间戳。同一份源码重新打包**逐字节一致**，所以 sha256 可以
  当包的身份用（缓存按内容寻址、锁文件可校验）。这条不是洁癖：打包不确定，
  "同版本不同哈希"会让锁与缓存同时失去意义。
- **本地目录按文件复制，http 用 GET/PUT**：发布走 `PUT packages/…` 再
  `PUT index/…`（先传包体，索引永不指向不存在的对象）；鉴权只有一个 Bearer
  token（环境变量 `QPM_TOKEN`），够用但不构成多租户权限模型。
- **索引缓存**：`~/.qpm/index/<url 摘要>/<name>.json`，TTL 由 `QPM_INDEX_TTL`
  （默认 300 s）控制；`--refresh` 忽略 TTL，`--offline` 只用缓存。
- **包体缓存**：`~/.qpm/cache/registry/<name>-<version>-<sha 前 12>`.qpk，
  命中后先验哈希再解包；哈希不符**拒绝安装**（不降级、不覆盖）。
- `QPM_CACHE` 可整体改缓存根（CI 与测试用它隔离）。

### 4.3 发布与撤回

```toml
[package]
name    = "mylib"
version = "1.2.0"

[deps]
beta = "^1.0"
```

```bash
python tools/qpm.py publish --registry local          # 打包 → 传包体 → 写索引
python tools/qpm.py publish --dry-run                 # 只打包，打印 sha256 与文件数
python tools/qpm.py yank mylib 1.2.0 --registry local # 撤回
```

- **同版本不可覆盖**：已存在就报错退出。改代码要发新版本；发错了用 `yank`
  ——`yank` 只让**新解析**不再选中它，已经锁住的工程仍能装（这是"撤回"而不是
  "删除"，历史构建可复现）。
- 发布不需要 git：包里是工作区当前内容（按打包规则过滤）。要"从 tag 发布"，
  自己 checkout 到干净目录再 `publish`。
- 约定：包名必须 import-safe（下划线，连字符不是合法标识符）；包根 = 工程根，
  `import <包名>.<文件>` 才能命中。

### 4.4 传递依赖与冲突合并（v1.99）

每个包自己的 `Quelmara.toml [deps]` 也读进来（registry 包用索引里的 `deps`
字段，不下载包体）。解析规则：

1. **同名依赖的所有区间取交集**，选满足全部区间的**最大**版本。
2. 新约束可能让已选版本失效 → 重选并重新展开它的依赖（贪心 + 定点迭代，
   最多 5000 步；不收敛即报错，不静默截断）。
3. git 依赖先**归一化成具体 rev**（区间先选 tag）再比较；path 依赖要求绝对
   路径一致；**同名依赖跨来源**（registry vs git vs path）直接报冲突。
4. **没有回溯**：区间无交集就报错，列出每条约束的来源与可用版本，不做
   "自动降级换版本"。静默换版本比报错难查得多。
5. **依赖环不是错误**：扁平布局里每个包只落一份，环可以安装；`install`/`tree`
   会打一行提示（升级时人工确认）。

冲突信息的形状（这是给人看的，不是给机器解析的）：

```
qpm: 依赖冲突：beta
      没有同时满足全部区间的版本：
        需要 ^2.0           （来自 <manifest>）
        需要 ^1.0           （来自 alpha 1.1.0）
      可用版本：1.0.0、1.0.1
      已 yank：2.0.1
      处理：放宽其中一条区间，或改 qpm add 的 spec
```

> 诊断是"一次说全"的：解析器在判定失败前会把队列里同名的待处理约束一起收进来，
> 所以不会出现"只报第一条、改完再报第二条"的挤牙膏。

### 4.5 锁文件与校验

`.qpm/lock.toml`（v2）：

```toml
[roots]
alpha = "^1.0"

[packages]
# kind|src|rev|sha|version|tree|deps
alpha = "registry|path:../qreg|1.2.0|<sha256>|<1.2.0>|<tree>|beta@^1.0;gamma@~2.1"
```

| 字段 | 含义 |
|---|---|
| `kind` / `src` / `rev` | 来源、来源地址、解析后的 rev（registry 即版本号） |
| `sha` | registry = `.qpk` 哈希；git = commit sha；path = 空（内容看 `tree`） |
| `version` | 包自己声明的版本（可能为空：老包没写 `[package]`） |
| `tree` | 安装后目录的**内容哈希**（relpath + 长度 + 内容，排序） |
| `deps` | `name@range`，`;` 分隔（区间内部的逗号不受影响） |

- `install --locked`：完全不解析，按锁落地；清单与锁不一致时**拒绝**并提示先
  `install`。它同时是"离线可复现构建"的入口（配合 `--offline`）。
- `verify`：锁 ↔ 清单 ↔ 磁盘三方对照。registry/git 包内容变了是**错误**；
  path 依赖的源改了是**警告**（`--strict` 才算错误），因为 path 依赖本来就是
  活代码，重新 `install` 即同步。
- `tree`：打印"解析后"的依赖树（带区间与版本），环处标注。

### 4.6 边界（做不到的写在这里）

- **一个项目只从一个 registry 解析**：`[registry].default` 或 `--registry` 选一个；
  多 registry 并存（同名包跨源择优）没做。
- **没有签名与公信链**：哈希只保证"索引说是什么就下什么"，索引被改就无从发现。
- **没有多租户权限**：只有一个 Bearer token，没有 scope/owner/团队概念。
- **没有构建钩子**：包只有源码，没有 `build.rs` 那类"安装时生成代码"的步骤。
- **没有增量**：`install` 每次重新解析 + 重新落地（`.qla` 目标文件格式仍未做，
  见 `07-gaps.md` §3）。
- 依赖版本冲突不做回溯求解，只做"交集 + 最大"（见 §4.4 第 4 条）。

测试：`python tests/qpm_test.py`（确定性打包 / 恶意包拒绝 / registry 发布 /
传递依赖 / 区间交集 / 冲突报错 / yank / 锁 / verify / HTTP 发布安装 /
装完能被编译器 import 并跑出结果）；`python tests/qpm_semver_test.py`
（版本与区间语义单测 + `file://` git 端到端）。性能见 `06-status.md` §3.13。

端到端夹具：`fixtures/qpm-demo`（路径依赖 + `file://` git 依赖两条路）。

## 5. 测试体系

### 5.1 夹具

| 目录 | 内容 |
|---|---|
| `tests/*.qma` | 139 个正向夹具，多数用 `assert` 自校验 |
| `tests/bad/*.qma` | 67 个负向夹具，**必须编译失败** |
| `examples/*.qma` | 18 个可运行示例 |
| `bench/*.qma` | 23 个基准 |
| `fixtures/` | 端到端工程夹具（srcproj / qpm-demo / lspdemo / dbgdemo …） |
| `fixtures/lspdemo/` | 语言服务器夹具：`main.qma` + 被导入的 `util.qma`（跨文件跳转/重命名），**同时能编译运行** |

### 5.2 脚本

| 脚本 | 作用 | 平台 |
|---|---|---|
| `tests/run_win_tests.py` | **主回归**：PE 结构 / 基础语义 / 语言特性 / 多核 / 单核降级 / fail-fast / 交叉验证 | Windows |
| `tests/run_native_tests.sh` | 自研 ELF 后端回归（含 AArch64 模拟器执行级） | Linux |
| `tests/run_tests.sh` | C99 后端回归（gcc -O2，仅交叉验证） | Linux |
| `tests/test_corelib.sh` | mem/mt/store 运行时回归 | Linux |
| `tests/test_uring.sh` | io_uring 网络回归 | Linux 5.1+ |
| `tests/lexdiff.py` | 词法器对拍（stage-0 vs 自举） | 全平台 |
| `tests/parsediff.py` | 声明级 AST 对拍 | 全平台 |
| `tests/irdiff.py` | QuIR 架构无关性对拍（`-j` 并行，默认按核数） | 全平台 |
| `tests/emitdiff.py` | 发射层确定性对拍 | 全平台 |
| `tests/bodydiff.py` | 函数体 dump 对拍（自举进度主线） | 全平台 |
| `tests/bodydig.py` | 函数级并排定位（bodydiff 的定位工具） | 全平台 |
| `tests/bodymatrix.py` | 语句形态支持矩阵（批处理） | 全平台 |
| `tests/gzip_interop.py` | gzip 与 zlib 逐字节互操作（编码方向） | 全平台 |
| `tests/gzip_inflate_test.py` | gzip/deflate 解码互操作（9 种编码组合 × 7 类输入） | 全平台 |
| `tests/gzip_http_test.py` | HTTP 压缩协商端到端 | 全平台 |
| `tests/ecdsa_p256_test.py` | ECDSA P-256 验签互操作（Python bigint 参考实现） | 全平台 |
| `tests/x509_test.py` | X.509 解析 + 自签验签互操作（手工 DER + bigint 签名） | 全平台 |
| `tests/x509_chain_test.py` | 证书链 + 有效期 + 域名（含通配符）验证，Python 手工三级链 | 全平台 |
| `tools/dev/tls_probe.py` | 真实服务器 TLS 1.3 握手探针（Python 提供 socket，手动运行） | 全平台（需网络） |
| `tests/a64_emu.py` | AArch64 指令模拟器 | 全平台 |
| `tests/a64_iface_test.py` | **AArch64 接口 vtable 执行级**：7 个接口夹具编译成 ELF 后真跑（装箱 / 异构容器 / 跨接口同名方法 / 所有权 / 跨文件 / 泛型 enum 载荷 / 1 MB 上限下的引用计数回收）；`--quick` 跳过最慢的低堆用例 | 全平台 |
| `tests/debugger_test.py` | 调试器脚本化会话（18 项期望 + 调试/非调试构建输出逐字节相同） | Windows |
| `tests/dbg_test.py` | 调试器端到端命令链（断点/三种不可读语义/单步/bt/退出码） | Windows |
| `tests/dwarf_test.py` | DWARF v4 互操作：独立读取器解析四个节，逐项对照 `.qlmdbg` | 全平台 |
| `tests/cov_test.py` | 行 + 分支覆盖率链路（未覆盖行/分支检出、函数级、增量合并、两种阈值门禁） | Windows |
| `tests/fuzz_test.py` | 模糊测试链路（用例确定性、变异生效、崩溃分类口径、端到端） | 全平台 |
| `tests/qpm_test.py` | **包管理全链路**：确定性打包 / 恶意包拒绝 / registry 发布（本地 + HTTP）/ 传递依赖与区间交集 / 冲突报错 / yank / `--locked` / `verify` / 装完能被编译器 import 并跑出结果 | 全平台（需 git） |
| `tests/qpm_semver_test.py` | 版本与区间语义单测 + `file://` 本地 git 端到端 | 全平台（需 git） |
| `tests/doc_test.py` | doc comment 链路（语法规则 / 前端挂载 / CLI / fmt 保留 / 产物逐字节相同） | 全平台 |
| `tests/lsp_test.py` | 语言服务器：全仓库词法对拍 / 容错索引 / 索引语义 / 真 JSON-RPC 协议 / 性能阈值 | 全平台 |
| `tests/cache_test.py` | 增量缓存：冷/热、改主文件、改依赖、改回原样命中旧条目、开关隔离、产物截断、`--stat/--clear`、串行=并行 | Windows |
| `tools/dev/incr_bench.py` | 增量/并行编译性能探针（单单元冷/热、多源 `-j`、`test -j`、进程创建基线，手动） | 全平台 |
| `tools/dev/doc_bench.py` | doc 扫描吞吐与编译期占比探针（手动） | 全平台 |
| `tools/dev/dbg_bench.py` | 调试链路性能探针（构建开销 / 体积占比 / 每命中 / 每步，手动） | Windows |
| `tools/dev/cov_bench.py` | 覆盖率与 fuzz 链路性能探针（分支表体积 / 采集开销 / 汇总耗时 / fuzz 吞吐，手动） | Windows |
| `tools/dev/own_bench.py` | 所有权检查探针：占编译时间比 / 产物逐字节（检查开·关）/ `_own_parts` 深度扫描（手动） | 全平台 |
| `tests/bench_gate_test.py` | 性能门禁自测：建基线 / 同产物判 PASS / 伪造 2× 回归必须 FAIL / 校验和与体积必须拦住 | 全平台 |
| `tools/dev/bench_gate.py` | 性能回归门禁（基线模式 + 同机 A/B 模式，见 §1.3） | 全平台 |
| `tools/dev/qexcmp.py` | 双向 `.qex` 对照：两个 worktree 各编同一批源文件，逐字节比产物（发射层改动"没波及别处"的硬证据，手动） | 全平台 |
| `tools/dev/qpm_bench.py` | 包管理性能探针：合成 registry 的解析（冷/热索引）、install 全流程、verify、确定性打包耗时（手动） | 全平台 |

### 5.3 门禁（CI 双平台都跑）

| 脚本 | 拦什么 |
|---|---|
| `tools/dev/check_names.py` | 旧项目名残留、`.ros` 扩展名残留、C 运行时符号自洽 |  <!-- legacy-ok -->
| `tools/dev/check_origin.py` | 只用标准库、无异语言运行时特征、无第三方目录 |
| `tools/dev/check_docs.py` | 过期断言黑名单、文档索引完整性、版本目录完整性、数字单一来源、`VERSION` 与版本目录同源 |
| `quelmara doc std --missing` + `gen_stdlib_doc.py --check --require-doc` | 公开 API 面缺 `///` 文档、doc 块脱离、`03-stdlib.md` 与源码漂移 |

```bash
python tools/dev/check_names.py
python tools/dev/check_origin.py
python tools/dev/check_docs.py
python tools/stage0/qlm_cli.py doc std --missing          # 公开 API 面缺 /// 就失败
python tools/dev/gen_stdlib_doc.py --check --require-doc  # 03-stdlib 与源码一致 + 覆盖
```

## 6. CI

`.github/workflows/ci.yml`，push 到 master 或 PR 触发，三个 job：

| job | 步骤 |
|---|---|
| `linux`（ubuntu） | 三道门禁 + 文档生成门禁 → 四套对拍（lex/parse/IR/emit）→ C 后端回归 → 自研 ELF 回归（含 A64 模拟器）→ 运行时回归（corelib + io_uring） |
| `windows` | 三道门禁 + 文档生成门禁 → PE 回归 → gzip 解码 / ECDSA / X.509 互操作 → 词法/声明级对拍 → `test --targets all` 多后端矩阵 |
| `perf`（windows） | 门禁自测（`tests/bench_gate_test.py`）→ 性能回归门禁（`--ab origin/<base>`，同机交错 A/B，阈值 20%） |

`perf` 单开一个 job 不是洁癖：A/B 要跑两棵树并交替计时，混在功能回归里会互相抢
CPU，把噪声变成红。基线模式（`--check`）只在**有对应基线的机器**上跑；CI runner
与参考机 CPU 不同，key 对不上会 SKIP 而不是误判——CI 上真正生效的是 A/B 那一档。

超时 30 分钟。本机没有 gcc/WSL，Linux 侧只能在 CI 上验证。

## 7. 本地开发循环

```bash
# 改完代码的最小验证
python tests/run_win_tests.py            # 主回归
python tools/dev/check_docs.py           # 文档门禁（改了文档必跑）

# 动 parser / 自举相关
python tests/lexdiff.py && python tests/parsediff.py && python tests/bodydiff.py

# 性能改动
python tools/stage0/qlm_cli.py bench bench/p0_bench.qma --runs 5 --update-baseline

# 改了 parser / 降级（模糊测试抓崩溃，2 分钟一批）
python tools/stage0/qlm_cli.py fuzz tests/t64_math.qma --cases 64 --seed 1
python tools/dev/bench_gate.py --check            # 门禁：与基线比（改完先跑这个）
python tools/dev/bench_gate.py --update           # 确认无回归后再更新基线
```

## 8. 发布与推送

- 推送：`git push` 直连时通时断（本机代理会拦 `github.com:443` 的 CONNECT）；
  稳定通道是 `python tools/dev/push_via_api.py`（逐 blob 建 tree/commit 再 PATCH ref，
  凭据走 Windows Credential Manager）。
- 产物是单文件可执行程序，无运行时依赖；版本号口径见 `qlm_cli.py version`
  （与 `docs/versions/` 最新目录同源，由 `check_docs.py` 门禁强制）。
