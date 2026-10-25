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
| `build` | 编译（可一次给多个源） | `src...`、`--target`、`-o/--out`（单源）、`--no-opt`、`--dump-ir`、`-j`（多源并发）、`--no-cache`；**v2.11**：`--emit-qla`（编译到 `.qla`）、`--lib`（二进制库）、`--incr`（函数级增量）、`--lib-input Q.LA`（链接二进制库） |
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
| `link` | 链接多份 `.qla`（v2.11） | `inputs...`、`-o/--out` |
| `qla` | 查看 / 校验 `.qla`（v2.11） | `--stat FILE`、`--symbols FILE`、`--verify FILE` |
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
目标文件格式 `.qla` 由 §1.8（v2.11）提供——它管"只重编变了的函数"和"分发二进制库"；
这一节管"什么都没改还全量重编"这件纯浪费的事。两个开关分别对付两件事：

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

- **单元级，不是函数级**：这一层省掉的是**整个单元**的编译，跨单元复用不做；
  函数级增量在 §1.8（`.qla`）。两者叠加：缓存未命中时，`.qla` 仍能复用没变的函数。
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

### 1.8 目标文件 `.qla` 与函数级增量（v2.11）

v1.100 的缓存省掉的是**整个单元**的重编；`.qla` 省掉的是**没变的函数**的降级与
优化，并让"分发二进制库"成为可能。两者叠加：缓存未命中时，`.qla` 仍能复用没变
的函数。

| 命令 | 作用 |
|---|---|
| `build src --emit-qla` | 编译到 `build/<名字>.qla`（QuIR + 全局区 + 符号表，**不发射机器码**） |
| `build src --lib` | 库档案：**不做 DCE**，全部函数 + 类型表进档案，可脱离源码分发 |
| `build src --incr` | 函数级增量：复用 `build/<名字>.qla` 里未变的函数 IR，产出 `.qex` 并把新档案写回 |
| `build src --lib-input lib.qla` | 把库档案的**签名与类型布局**注入编译期（不拿实现） |
| `link a.qla [b.qla…] -o out.qex` | 多份档案 → 一个可执行文件 |
| `qla --stat / --symbols / --verify` | 统计与元数据 / 导出符号表 / 校验和 |

```bash
python tools/stage0/qlm_cli.py build src/mylib.qma --lib -o build/mylib.qla
python tools/stage0/qlm_cli.py qla --symbols build/mylib.qla
python tools/stage0/qlm_cli.py build src/app.qma --lib-input build/mylib.qla -o build/app.qex
python tools/stage0/qlm_cli.py build src/app.qma --incr      # 改一行 -> 只重编那个函数
python tools/stage0/qlm_cli.py link build/app.qla build/mylib.qla -o build/app.qex
```

#### 容器格式（`tools/stage0/qlm_qla.py`）

```
QLA1\n
<header json>\n      format / unit / kind(program|lib) / arch / platform / opt /
                     compiler（编译器指纹）/ cfg（配置摘要）/
                     payload_sha256 / sections[{name,off,len,sha256}]
<payload>            meta 段（JSON）+ 全局数据段（裸字节）
```

`meta` 段：函数记录（`name/hash/needs/ir/nv/frame_words/structv/no_inline/
iface_fresh/iface_own/closig/win_thread/owner/inl`）、全局块长度表、vtable、
进程级单例全局字的 gid、计数器、导出符号表、类型表、未定义符号、字符串池映射。
IR 是 QuIR 的 JSON 形态（元组 ↔ 数组严格互逆）。

- **确定性**：`sort_keys` + 无时间戳 + 无绝对路径 ⇒ 同源码同编译器**同字节**，
  sha256 即身份（可当内容寻址的键）。
- **自校验**：段级 sha256 + payload sha256 + 长度表。截断/拼接/损坏一律在
  `Archive.load` 报错，不会把半截 IR 交给发射层。
- **不含机器码**：档案到 `.qex` 之间还有一次 Codegen，所以同一份档案可以按
  不同入口/不同档案组合反复链接。

#### 函数级增量：怎么判定"这个函数不用重编"

一个函数的哈希 = H(自身 AST + 类型环境摘要 + 它引用到的函数签名) 再叠加内联传播：

| 组成 | 为什么在里面 |
|---|---|
| 自身 AST（去 `doc`/`line`） | 函数体、形参、返回类型、impl 信息。注释与行号不影响代码，改了不必重编 |
| **类型环境摘要** | 编译器指纹 + 架构/平台/优化档 + 配置摘要 + **类型表**（struct/enum 布局）+ 接口表 + 析构表。字段一加，布局全变 → 全部失效（保守但正确） |
| **被引函数的签名** | 只收它**真正引用到的**函数，不是整张签名表——否则"加一个函数"会让全库失效 |
| **内联传播**（`inl` 表） | 内联把 callee 的函数体搬进了 caller，callee 一变 caller 的 IR 也必须变。档案里每个函数记下"内联进来的 callee 名单"，复用时沿这张表做不动点 |

内联传播是**正确性要求**，不是优化：实测反例——把 helper 的 `a * 2` 改成
`a * 3`，不做传播时被内联的 `use` 仍然算旧值（产物能跑、结果是错的）。
所以"改小函数"会连带重编调用链；改**大函数**（>28 条 IR 且多个调用点，不会被
内联）才是"只重编它自己"。

复用时要接管三样状态，少一样产物就与全量构建不一致：

1. **全局数据区 + 字符串池映射**（`gid_of_str`）：否则重降级的函数会把同一份
   字面量再 intern 一遍，数据区里出现重复块。
2. **进程级单例全局字**（`argc`/`argv`/`static_word`/空闲链/`args` 拷贝标志）：
   `args()` 必须读到入口写的那一份。
3. **计数器**（`lam_seq`/`spawn_id`）：否则新旧两份 `__lam_N` 撞名。

运行库 helper（`__alloc`/`__vec_*`…）**永远复用**——它们的 IR 只由编译器指纹 +
平台 + 配置决定，与用户源码无关。全部函数都复用时连运行库都不重发（不新开全局
字），产物才与全量构建**逐字节相同**。

#### 二进制库：链接是名字解析

- `build --lib`：不做全局 DCE（库没有入口），全部函数 + 类型表进档案；
  `exports` 只收 `pub` 声明（`qla --symbols` 看到的就是它，非 pub 的内部
  函数在档案里但不在符号表里）。
- `--lib-input lib.qla`：注入**类型表**（同名类型布局必须一致，否则报冲突）与
  **函数签名存根**（`body=None`，实现留给链接期）。本文件有同名定义时本地优先。
- `link`：
  1. 按单元基址重编 gid——`("ga", gid)` **元组**与 `movaddr` 的**裸 gid** 都要改
     （漏后者会让跨库字符串指到别人的数据区，实测打成 `qlaqla`）；
  2. 进程级单例全局字统一指向第一个档案；
  3. 同名函数按"忽略 gid 的结构签名"去重（于是运行库 helper 全进程只有一份：
     一个堆、一份空闲链），签名不一致则报**符号冲突**而不是随便挑一个；
  4. vtable 合并；`__vt_接口__类型` 是 Codegen 现发的表，不算未定义符号；
  5. 收尾检查：`main` 唯一、无未定义符号。

#### 边界（做不到的写在这里）

- **仅 `--target win`**：IR 与 ABI 都按 PE/x86-64 固化；`--dbg-info` 不走档案。
- **档案不跨编译器/跨配置复用**：指纹或配置摘要不符直接报错，不猜。
- **增量下限是解析**：哈希按 AST 算，仍要读全部源码。解析器目前一个文件读三遍
  （宽松扫描 / 严格重解析 / `_consts_of`），这是下一步（解析缓存）的空间。
- **无跨档案内联**：内联只在各自编译单元内做；链接期不重跑内联。
- **泛型模板与 `const` 不从档案导出**：`const` 在解析期内联（已经在 IR 里），
  泛型模板要实例化，跨档案传递需要新的档案段，未做。
- **无档案级调试信息**：链接产物不带 `.qlmdbg`（断点调试仍走源码构建）。

回归：`tests/qla_test.py`（32 条：往返逐字节、函数级增量四种形态、二进制库
无源码链接、7 条失败路径、CLI）。性能：`tools/dev/qla_bench.py`，数字见
`06-status.md` §3.22。

### 1.9 服务端运行时（reactor）在标准库里（v2.12）

**改哪里**：`std/net/reactor.qma`。IOCP 事件循环、连接记录池、accept 循环、完成包
派发、关闭路径全在这个文件里，用 Quelmara 写。stage-0 只剩三个原语：

| 原语 | 作用 |
|---|---|
| `@ffi`（v1.87） | `CreateIoCompletionPort` / `GetQueuedCompletionStatus` / `WSARecv` / `WSASocketW` / `bind` / `listen` / `accept` / `closesocket` / `setsockopt` / `WSAStartup` / `WSAGetLastError` |
| `thread_start(fn, arg)`（v2.12） | 起 N 个 worker。**不受 `multicore=false` 降级**——`spawn` 在单核配置下会内联执行，主线程就再也回不到 accept |
| `net_config(key)`（v2.12） | 编译期读 `[net]`：`0` max_conns / `1` recv_buffer / `2` io_threads（已解析）/ `3` tcp_nodelay |

**分层（别合并）**：

| 模块 | 内容 | 可移植性 |
|---|---|---|
| `std/net.qma` | 阻塞式 `listen` / `accept` / `send` / `recv` / `connect` | 不含 `@ffi`；`tcp_*` 内建目前仍只有 Windows 实现 |
| `std/net/reactor.qma` | IOCP reactor：`net_serve` / `serve` | **仅 Windows PE**（`@ffi`） |
| `std/net/core.qma` | 协议库共用的槽位层（640 B/连接） | 纯内建，可移植 |

`std/http` / `std/ws` / `std/sse` 都 `import std.net.reactor`；`std/net.qma` **不** import
它。理由不是"现在就能编 Linux"（`tcp_listen` 内建在 native 上仍会报
`无法发射指令 ('winapi', … 'WSAStartup')`），而是**别让 IOCP 绑定钉死 net 模块**：
`@ffi` 在非 Windows 目标是声明期硬失败，并进来之后 Linux 侧接 epoll 也永远编不过。
与 `std/log` / `std/logfile` 的拆法同源。

**多核默认**：worker 数 = `[net] io_threads`（`0` → `core.threads` → 物理核数）。
完成端口**共用一个**：per-reactor（每线程一个端口）实测更差，见 `06-status.md` §3.23。

**测**：先起服务端再压客户端——

```bash
python tools/stage0/qlm_cli.py build bench/echo_bench.qma --target win -o build/echo_bench.exe
build/echo_bench.exe &
python tools/dev/net_bench.py echo --conns 4 --reqs 300        # 往返
python tools/dev/net_bench.py echo --conns 32 --reqs 200 --threads 4   # 吞吐
```

多核标定用 `bench/net_cpu_bench.qma`（handler 里烧固定 CPU，吞吐随 `io_threads` 走）；
改 `[net] io_threads` 后重编才能生效——它是**编译期常量**。

### 1.10 原生驱动器 `qlm.exe`（v2.13）

`bootstrap/driver/qlm_drv.qma` 编译出的 `build/qlm.exe` 把**入口**从 Python 换成
Quelmara：先在原生代码里判"输入有没有变"，没变直接复用产物，变了才委托 stage-0。
动机是实测的启动成本——本机 `python -c pass` 561 ms、`import qlm_native` 1740 ms，
而"源码没动"时编译器其实无事可做（数字见 `06-status.md` §3.24）。

```bash
python tools/stage0/qlm_cli.py build bootstrap/driver/qlm_drv.qma --target win -o build/qlm.exe
build/qlm.exe run examples/hello.qma      # 变则编、不变则直接跑（开发主循环）
build/qlm.exe build examples/hello.qma    # 只保证产物最新（不跑）
build/qlm.exe stat examples/hello.qma     # 打印闭包、各输入 mtime、判定与自身耗时
build/qlm.exe version
```

**判定规则**（宁可重编，不可给旧产物）：产物 `build/.drv/<源路径转义>.exe` 比
**全部输入**都新就复用；输入 = 源文件 + 递归 `import` 闭包 + 编译器 5 个核心 `.py`
+ `Quelmara.toml`。闭包里出现**解析不了的模块**（`src/` 根、第三方包）→ 一律重编。
`--force` / `-f` 跳过判定直接委托。

**边界**：

- **它不是编译器**：类型推断 / 降级 / 优化 / 编码 / PE 写出仍在 stage-0（组件自举进度见
  `06-status.md` §4）。它自举的是驱动器，不碰语义。
- 闭包解析只认 `std.*` 与同目录兄弟模块；解析不了就重编（fail-safe）。
- 判新鲜度用 **mtime** 而不是内容哈希：读 1 MB 源码算哈希在原生侧也要十几毫秒，
  而"改编译器必然改 mtime"这条前提在开发循环里成立。
- 命令行里的路径必须转成 `\\`：`system()` 走 cmd.exe，不认 `build/hello.exe`
  （实测报"不是内部或外部命令"并把退出码吞成 1）。

### 1.11 stage-1 编译器 `qlmc`（v2.38：真 IR + 线性扫描 + 多核，子集 S20；**自举不动点达成**）

`bootstrap/qlmc/qlmc.qma`（约 3.3 千行 Quelmara）是一个**能出 exe** 的编译器：
`.qma` -> PE32+，全程本语言，不经过 Python、不链接 CRT、不依赖第三方。
它自己先用 stage-0 编出来（`build/qlmc.exe`），之后用它编别的程序。

```bash
python tools/stage0/qlm_cli.py build bootstrap/qlmc/qlmc.qma --target win -o build/qlmc.exe
build/qlmc.exe build examples/fib.qma -o build/fib.exe     # -j N 可指定线程数
build/qlmc.exe dump  examples/fib.qma                      # 只跑词法+语法，打印统计
build/qlmc.exe version
```

**流水线**（改哪一层一目了然）：

```
.qma ─lex─▶ 记号 ─parse─▶ 平坦 AST ─lower─▶ 三地址 IR ─alloc─▶ 带位置 IR ─emit─▶ 机器码
                                                                  │
                                                       按函数分片并行（每线程一段 arena）
```

| 层 | 位置 | 做法 |
|---|---|---|
| 词法 | `lex` | 只认 S2 的记号集；不认识的字符 fail-fast（不静默跳过） |
| 语法 | `parse` / `_expr` / `_stmt` | 递归下降 + 优先级爬升；**平坦 AST**（节点表 + `nx` 链），块用链不用区间 |
| 降级 | `_lower_expr` / `_lower_into` / `_lower_cond` | AST → IR。`_lower_into` 把赋值**直接算进目标变量**，`_lower_cond` 直接发 `cmp+jcc` |
| IR | `Ir { op, dst, a, b, imm }` | 26 个操作码：常量 / 搬运 / 算术 / 比较 / 标签 / 跳转 / 条件跳 / 实参 / 调用 / 返回 / 打印 / 退出 / 取址 / 取长度 / 入参 |
| 分配 | `_alloc` | **两段式**：变量固定 callee-saved（RBX/R12-R15，满了落帧槽）；临时值按活跃区间线性扫描（R8-R11），**跨调用**的临时值直接落帧槽 |
| 发射 | `_emit_ir` / `_emit_fn` | x86-64 手写编码（REX/ModRM/SIB、rel32 回填）；操作数按位置选 reg-reg / reg-mem 形态 |
| 并行 | `_compile_range` | 每个线程编一段函数，写 arena 里自己那段；主线程按函数序拼装 + 统一回填 |
| 文件 | `build_rdata` / `build_pe` | **三节**（`.text`/`.rdata`/`.bss`）、导入表（kernel32 + user32）、PE32+ 头；`.bss` 1 MB 当堆（不占文件体积） |
| 运行库 | `_gen_*` | 8 个手写例程：print_i64（`wsprintfA("%I64d\n")`）/ print_str / **print_bool** / memcpy / alloc（bump）/ str_cat / str_eq / die。全走 Win32，不引 CRT |

**寄存器分配的两条硬规则**（改分配器前先读）：

1. **变量固定、临时扫描**。变量在函数内固定一个 callee-saved 寄存器——这样跨循环、
   跨调用都成立，不需要 SSA 与 phi。临时值只在 `[首次定义, 最后使用]` 区间内占寄存器。
2. **区间跨调用的临时值不许进 caller-saved**。判断用调用前缀和：
   `cp[end+1] - cp[start+1] > 0` 即区间 `(start, end]` 内有调用 → 直接落帧槽。
   这条替代了「在调用点插溢出代码」，是并行/正确性都最省的做法。

**发射器保留的暂存**：RAX（除法 / setcc / 打印值）、RCX（实参 0 / 打印 str）、
RDX（实参 1 / 除余）。这三个**永不被分配**，所以发射序列不会踩到已分配的值。

**并行与确定性**（这是"多核"的全部内容）：

```
arena（mem_alloc 16 MB）
  [0 .. 63]        线程表：每线程 8 字（lo, hi, base, cap）
  [64 .. ]         函数表：每函数 7 字（code_off/len, lab_off/len, fix_off/len, region_base）
worker w         只写 [base, base+cap) 这一段 → 线程之间零共享可变状态，无需锁
                 每函数写自己那 7 字 → 无竞争
main             按 fi 升序拷字节 + 回填 → 线程数不影响产物字节
```

- `-j N` 强制线程数；省略或 `-j 0` = 自动：**每线程约 50 个函数**才开线程，
  函数少于 16 个直接单线程（线程创建 ~200 µs/个，小输入上并行是负收益）。
- `-j 1` 与 `-j N` 走**同一条代码路径**（只是不 spawn），所以产物逐字节相同。
  这条由 `tests/qlmc_test.py` 的「并行确定性」段钉住。
- 并行只覆盖**函数体**：词法 / 语法仍是单线程，是当前墙钟的主要部分。

**支持（S20）**：

| 类别 | 覆盖 |
|---|---|
| 声明 | `fn`（**形参不限个数**：前 4 个走 RCX/RDX/R8/R9，第 5 个起走栈；int/bool/str 形参与返回）、`const`（**整型常量表达式**，解析期折成一个整数后内联）、**`struct`（≤8 字段，字段限 int/bool/str）** |
| 语句 | `let`/`mut`（可带类型标注，可省初始化）、赋值、`if`/`else`、`while`、**`for i in lo..hi`**、**`break`/`continue`**、`return`、`exit`、表达式语句、**`else if` 链**、**`spawn f(args)` / `join(h)`（真线程）** |
| 内建 | `print` / `eprint`（int/bool/str）、`len`、`assert(cond, msg)`（失败写 stderr 后退 1）、`exit`、`join(h)`；**内存原语** `mem_alloc` / `mem_free`（bump，不回收）/ `mem_load8` / `mem_store8` / `mem_load64` / `mem_store64` / `mem_copy` / `mem_zero` / `mem_cmp` / `mem_str`；**串** `chr` / `substr` / `cstr`（恒等）/ `int.to_str` / `str.to_int`；`file_exists` / `now_ns`；**`s[i]` 字符串下标**（按字节、越界 fail-fast） |
| 类型 | int（64 位）/ bool / str（`[len][bytes][NUL]`，值 = 数据指针）/ **byte** / **f64** / **struct** / **`[N]T` 定长数组** / **enum** / **`vec[T]`** / **`map[K]V`** / **`[]T` 切片** / **`fn`（无捕获闭包）** |
| 聚合 | **struct 字面量 / 字段读写 / 值语义拷贝**、**数组字面量 / 下标读写**、**enum 构造 / match**、**`vec[T].new(n)` / `.push` / `.get` / `.set` / `.len()` / `v[i]` 读写 / `len(v)`**（**容量可变：满了自动翻倍**，`new(0)` 起步也可；**元素可以是 struct/enum/定长数组**，步长按 `_ty_size` 算）；**结构体字面量可当值用**（push/set/实参位置）；**聚合可作形参与返回值**（按值传 + `sret` 隐藏指针）、**`map[K]V`**（new/set/get/has/len，**满了自动翻倍**，v2.43）、**切片 `[]T`**（`a[lo..hi]`、下标读写、作形参、视图不拷贝）、**`defer`**（块级、LIFO、`return` 前跑但返回值先定）、**`import`（同目录多文件，逐级向上找源根）**、**`@ffi("dll","Sym")`（任意 DLL，导入表数据驱动）**、**闭包（`fn(...)->T{...}`，无捕获）**、**`spawn` / `join`（真线程）**；聚合值一律在帧里，"值 = 区域地址" |
| 运算 | `+ - * / %`（int）、`+`（str 拼接，走堆）、`== !=`（str 走内容比较）、
`< <= > >=`、`&& \|\| !`（短路）、一元负号、**`& \| ^ ~ << >> >>>`（位运算/移位）**、
**f64 的 `+ - * /` 与六种比较**（含 int/f64 混合时的隐式提升） |
| 其它 | 递归与互调用、数字分隔符、单行注释、`module`（忽略） |

**不支持**：泛型、**闭包捕获**、宏/反射、接口、`rc`/`Drop`、
**嵌套聚合类型**（`vec[vec[T]]`：类型码 `TY_VEC+TY_VEC` 落进 `TY_MAP` 区间，见 §7.18）、
**聚合的 `print`**、**match 穷尽性检查**、`pub` 可见性与限定调用 `mod.fn()`、
错误信息带列号、常量折叠 / 强度削减 / CSE。
**`f64 % f64` 也不支持**——但 stage-0 同样报"浮点不支持运算符 %"，所以这是**口径一致**，
不是 qlmc 的缺口。

**能用但差分测不到的**（stage-0 那边丢类型，见 §7.28）：`vec[f64]` / `map[K]f64`
的元素——qlmc 取出来就是 f64、算术和打印都对，stage-0 会把元素当 int 打印成位模式。

**口径对齐（差分逼出来的）**：`&&`/`||` 与 **str 比较**产生 bool（打印 `true`/`false`），
而 int 比较与 `!` 产生 int（打印 `1`/`0`）——这是 stage-0 的实际行为，qlmc 照抄，
不"统一"。

**怎么验**：`python tests/qlmc_test.py` —— 同一份源码分别用 stage-0 与 qlmc 编，
**f64（v2.38 数值 / v2.42 打印）**：字面量（`1.5` / `1e3` / `2.5e-2`）、`+ - * /`、
六种比较、`to_float(x)` / `to_int(x)`、struct 字段、函数形参/返回值、**`print(f64)`** 都支持。设计上有两个要点：

- **f64 一律住在 8 字节帧槽里，按"地址"传递**（当聚合对待）。qlmc 的分配器只管通用
  寄存器，f64 要用 XMM —— 那套双寄存器文件 + 调用约定是另一个量级的改动。每次运算把
  操作数 `movsd` 进 xmm0、对右操作数直接带内存操作数算，算完存回槽。先要"对"。
- **字面量的 IEEE 位由运行时的 `strtod` 解析**（msvcrt），不在编译期算：qlmc 只会整数
  算术，要自己算就得实现正确舍入的十进制→二进制转换。交给 strtod 既正确、又和
  stage-0（Python float 解析）逐位一致，差分才对得上。代价：字面量在运行时解析一次。
- **`print(f64)` 是手写机器码**（`__f64_fmt`）：`wsprintfA` 不支持浮点、msvcrt 的
  `sprintf` 在无 CRT 上下文里写不出东西（§7.26 有实测记录）。口径对齐 stage-0 的
  `__f64_to_str`：`|x| == 0` → `0`；NaN → `nan`；±inf → `inf`/`-inf`；
  `1e-6 <= |x| < 1e12` → 定点（6 位小数 + 去尾零）；其余 → 科学计数。
  **小数那 6 位只碰低寄存器**（rcx/rdx/rax）—— 用 r9/r10 做下标会漏 REX 位。

比较 stdout 与退出码**逐字节相同**（26 组用例 55 条），外加并行确定性 2 条
（`-j1` 与 `-j4` 产物 `cmp` 相同 + `-j4` 产物运行结果）。这是唯一有说服力的判据：
"能出 exe"很容易，"和既有编译器行为一致"才是真的对。

**为什么先做"能跑通 + 后端真"再做"覆盖全"**：后端是承重墙——IR 与分配立起来之后，
加语法只是加 `_lower_stmt` 一个分支；反过来先把语法铺满再换后端，等于两遍返工。

**几个踩过的坑**（改这个文件前先看）：

1. **`vec` 元素不能当可变单元格**：`ps[0].pos = x` 写进的是临时副本，静默不生效。
   位置状态要用 `vec[int]` + `.set()`。
2. **`vec` 没有下标赋值**（`v[i] = x` 只对定长数组/切片成立），要用 `.set(i, x)`。
3. **PE 可选头的六个版本 u16 一个都不能少**：少一对会让后面字段整体前移 4 字节，
   加载器直接报"不是有效的 Win32 应用程序"。
4. **`wsprintfA` 不认 `%lld`**：64 位要用 `%I64d`；写错时它原样输出 "ld"。
5. **`fn` / `arena` 是关键字**，不能当变量名或形参名（`resolve_fn(arb, …)` 就是这么改的）。
6. **入口必须落在 `.text` 偏移 0**（`AddressOfEntryPoint` 恒等于 `TEXT_RVA`）：
   先发入口再发运行库。
7. **手写 REX 前缀别漏**：`test r8, r8` 是 `4D 85 C0`，写成 `48 85 C0` 就是 `test rax, rax`。
8. **运行库的实参寄存器要在调用点摆好**：`__str_cat` 要 RCX/RDX，先 `mov rdx, rcx`
   再 `mov rcx, rax`，反了会覆盖左操作数。
9. **结构体是按值传的**：`ctx.some_int = x` 写的是副本（静默失效）。可变标量状态
   放 `vec[int]` 单元素 cell（`.set` 写句柄），要么从函数返回。
10. **并行两处基准必须分清**：工作线程写的是**区域相对偏移**，主线程回读要按
    `region_base` 换算。v2.16 第一版就是这里错位，现象是"任何程序都 vec 越界"。
11. **常量名会撞**：新 IR 操作码别用 `I_*`——`I_EXIT`/`I_WRITE`/`I_GETSTD`/`I_WSPRINTF`
    已经是导入表槽位，撞了会让 `iat.set(I_EXIT, …)` 写到下标 21（越界或静默写坏）。
    新操作码统一 `OP_*`。
12. **函数基址不是 0**：拼装时函数体接在「入口 + 运行库」之后，`off` 的初值必须是
    当前 `.text` 长度；写成 0 会生成一个"能出但一跑就崩"的 exe。
13. **`fn` / `arena` 之外，`for` 的循环变量名也不能叫 `fn`**：`let fn = nodes.get(f)`
    直接语法错。后端里用 `fd`。
14. **前后端不能有同名函数**：`_st_nf` 在解析器（吃 `P`）和后端（吃 `FnCtx`）各有一份，
    后定义的那个会覆盖前一个——解析器调用时按 `FnCtx` 的字段偏移读 `P`，表现成
    "任何 struct 程序都 vec 越界"。前端专用函数一律带 `p` 前缀（`_pnf`）。
15. **AST 节点常量 E_\* 与 S_\* 共用一个数字空间**：`E_ARM=15` 撞过 `S_PRINT=15`
    （现象：`print` 被当成 match 臂）。新增节点先看号段（E_\* 在 40+，S_\* 在 10..23）。
16. **`FnCtx` 的字段数有上限（约 24）**：涨到 28 字段后，按值传递时被调方读到垃圾指针，
    现象是"单函数能编、两函数必崩"，且 `--no-opt` 同样崩。v2.18 把 6 个计数器并进
    `cells` 数组压回 22 字段才恢复。要加状态就往 `cells` 里加索引。
17. **函数签名的类型必须用 `_type` 解析**：早期用的是只认 int/bool/str 的 `_ty_id`，
    于是 `l: Light`、`p: Point` 被静默当成 int（v2.14–v2.17 一直如此）。
18. **按值拷贝形参时别踩实参寄存器**（v2.20）：`OP_ADDRV`/`OP_COPY` 的临时值落在
    R8-R11，而 R8/R9 就是第 3/4 个实参寄存器——先拷贝会把还没读的实参覆盖掉。
    必须**两遍收参**：先把所有入参落进 pinned 变量，再做拷贝。
19. **区间式类型码：新增类型码必须同步改 `_ty_is_agg`**（v2.26 才发现）：`_ty_is_agg`
    漏了 `TY_SLICE`/`TY_FN` 两个区间，切片因此"只占 8 字节槽却写 16 字节"，靠相邻槽
    空闲侥幸通过全部用例；闭包把它引爆。判定函数请按区间写（标量 = 0..3 + vec/map 句柄，
    其余聚合）。
20. **新增"会清 caller-saved 的指令"必须同步改 `_alloc`**（v2.25）：跨调用判定只认
    `OP_CALL`/`OP_CALLRT`，加了 `OP_CALLIAT` 却忘了登记，于是"两次 ffi 调用相加"把第一个
    结果留在了 caller-saved 寄存器里被清掉（`metric(0)+metric(1)` 算出 2016 而不是 3000）。
21. **`OP_CMP` 的 `imm` 是 setcc 码（0x9x），`OP_JCMP` 的 `dst` 是 jcc 码（0x8x）**（v2.27）：
    两者差 0x80。给 `OP_CMP` 传了 `0x1C`（本该 `0x9C`），编出来的是 `0F 1C C0`——
    **不是非法指令**，是 Intel 的多字节 NOP，CPU 照跑不误，只是比较结果变成"上一次的 AL"。
    现象是扩容的新容量恒等于下限 4，于是每次 push 都扩容、还按 `len*8` 拷贝越界，
    数据被搅成周期 4 的重复串。**两个发射器现在都带条件码范围守卫，写错直接 exit(2)**。
    排查手段：`python tools/dev/dumpasm.py exe 起始RVA 结束RVA` 反汇编（capstone 停在
    第一个非法字节，停下的位置就是问题指令）。
22. **vec 的布局必须是"头块 + 独立数据块"**（v2.27）：早期是 `[len][cap][data...]` 单块，
    数据紧贴头后面，一扩容就得整块换掉、句柄随之变化——别名变量（`let w = v`）立刻悬垂。
    现在头块 24 字节 `[data][len][cap]`，扩容只改 `[h+0]`/`[h+16]`，句柄恒定。
    改布局时别忘了三处硬编码偏移：`_vec_field` 的调用点、`_vec_elem_addr`（现在收
    **数据指针**而不是句柄）、以及 vec 切片的基址。
23. **词法/解析的热循环里不许用 `substr` / 字符串比较**（v2.28）：`substr` 每次分配
    一个新串。加 `>>>` 三字符判断时顺手写成 `substr(src,i,3) == ">>>"`，这段代码
    对**每个字符**都跑，结果 96 KB 输入从 16 ms 涨到 **54 ms（3.3×）**，还白吃堆。
    改成直接比字节（`src[i] == 62 && src[i+1] == 62`）后回到 16.1 ms。
    **判据：跑 `tests/selfhost/s3_manyfns.qma` 的编译耗时**——它对词法成本最敏感。
24. **运算符优先级照 stage-0 抄，别按 C 的直觉写**（v2.28）：Quelmara 的定义是
    `||` < `&&` < `|` < `^` < `&` < `== !=` < 关系 < `<< >>` < `+ -` < `* / %`
    （见 SPEC §2.4，`tools/stage0/qlm.py` 的 `parse_bor/bxor/band/shift`）。
    这**不是** C 的层次：C 把 `& ^ |` 放在 `==` 之下、`<<` 放在 `+-` 之上。
    写错的表现不是报错，而是差分里某一行数字对不上——例如 `6 & 2 == 2`
    在 Quelmara 里是 `6 & (2 == 2)` = 0，按 C 理解会算成 `(6 & 2) == 2` = 1。
    **新增运算符时先读 stage-0 的解析链，再抄顺序。**
25. **qlmc 的序言是「先 push callee-saved，最后 push rbp」**（v2.29）：所以
    返回地址在 `[rbp + 8 + 8*nsaved]`，**不是** `[rbp+8]`；第 5 个形参在
    `[rbp + 48 + 8*nsaved]`。第一版栈形参直接写死 `[rbp+48]`，5 个 callee-saved
    全用上时正好读成"保存的 r15"，现象是 5 实参函数返回一个像指针的巨大数字。
    `nsaved` 要到发射期才知道，所以 `OP_PARAMSTK` 的 imm 只记"第几个栈实参"，
    字节偏移由 `_emit_ir` 现算（`fc.cells[C_NSAVED]`）。
26. **`OP_ARG` 会写 RCX/RDX/R8/R9，而 R8-R11 正是临时值寄存器**（v2.29）：
    ① 聚合返回的 sret 指针**必须最后才搬进 RCX**——放在实参求值之前会被实参里的
    任何一次调用冲掉（现象：把结果写到地址 1，直接 AV）；
    ② 任何要活到 call 那一刻的值（sret 地址、闭包地址）**必须 `_pin`**，否则
    摆实参时被 R8/R9 覆盖。

27. **"值 == -1" 不能当"没找到"的哨兵**（v2.30）：`_const_of` 原本用 -1 表示
    "常量未定义"，于是 `const NEG = -7` 一旦被引用就被当成未定义变量（静默错编成
    "未定义变量"）。改成 `_const_idx` 返回**下标**（-1 = 没找到），值另取。
    凡是"查表返回单个 int"的辅助函数都要先想清楚哨兵会不会和合法值撞。

28. **`vec` 的元素步长不是常量 8**（v2.31）：`OP_ADDRX` 的 `shl rcx, 3` 只对
    8 字节元素成立。聚合元素（`vec[Struct]`）要按 `_ty_size(elem)` 走
    `OP_ADDRXN`（`imul rcx, rcx, imm32`）；`new`/`grow` 的字节数、`push`/`get`/
    `set` 的拷贝长度也全都得跟着步长走。**漏一处就是"下标越大错得越离谱"**。
    另外聚合元素在槽里存的是**值**不是指针，push/set 必须整块 `OP_COPY`。
29. **"字段/元素类型必须是标量"的检查要用 `_ty_is_agg`，不能用 `>= TY_STRUCT`**
    （v2.31）：`vec[Tok]` 是**标量**（8 字节句柄），但它的码 `0x8000+...` 大于
    `TY_STRUCT`，被旧检查误伤——而 qlmc 自己的 `struct P { toks: vec[Tok] }` 正是
    这个形状。凡是"只收标量"的门都要问一句"句柄算不算标量"（答案是算）。

30. **`[base+disp]` 的基址是 RSP/R12 时必须发 SIB 字节**（v2.32）：ModRM 的
    rm=100 是"SIB 跟在后面"的标记，不发 SIB 的话 disp32 的第一个字节会被当成
    SIB 解析，**整条指令连同后面全部错位**（反汇编看上去像一串无关指令）。
    `_lea_rm` / `_mov_load` / `_mov_store` 原来都没管这个，因为基址一直是 RBP；
    v2.32 的 `_lower_spawn` 用了 4 个 pin，第二个落到 R12，直接炸出段错误。
    现在统一走 `_modrm_mem`。
31. **stage-0 对 qlmc 源码的微小改动敏感——既有崩溃面（§7.17）也有性能面**（v2.32）：
    `_lower_spawn` 里两处 `eprint("…" + expr)` 字符串拼接，让 `s3_manyfns` 的编译
    从 **19 ms 涨到 33 ms（1.8×）**——而这段代码**从不执行**。删掉拼接就回到 18.7 ms。
    更邪门的是它不是单调的：同一函数体只留前 3 行（含拼接）慢、多留 10 行反而快。
    所以**改完 qlmc.qma 必须量 `s3_manyfns` 的编译耗时**（`-j1`，min of 3），
    它是唯一能发现这类"性能层面布局敏感"的判据。

32. **摆实参必须「先栈后寄存器」**（v2.33）：栈实参的值可能正躺在 R8/R9 里
    （那是临时值寄存器），而 `OP_ARG` 会写 R8/R9。先摆寄存器实参就会把还没落栈
    的值冲掉。实测形态：`ReadFile(h, buf, sz, got, 0)` 的第 5 个实参被写成了 `sz`，
    于是 `lpOverlapped = 226`，进程直接崩（fault_probe 报「写 0xE2」，反汇编里是
    `mov [rsp+0x20], r8`，而 r8 刚被上一个实参覆盖）。**顺序：STKARG 全写完，再 ARG。**

33. **寄存器实参 2/3 的临时值必须先钉住**（v2.34）：实参 2/3 的目标是 R8/R9，
    而临时值**正好住在 R8-R11** —— 把实参 2 搬进 R8 会冲掉还没搬的实参 3。
    实测：`f(a, b, c, 4)` 的第 4 个实参传成了 `c`（`_modrm_sib(code, mod, reg)`
    内部调 `_modrm(code, mod, reg, 4)` 就踩这个，于是整个 SIB 编码错位）。
    修法：摆实参前把下标 2/3 的**临时值** `_pin` 进变量（下标 0/1 的目标是
    RCX/RDX，临时值不会住那儿）。这是坑表 #32 的姊妹条。
34. **RIP 相对位移是相对「整条指令末尾」**（v2.34）：`mov qword [rip+disp], imm32`
    在 disp32 后面还跟 4 字节 imm32，而 `_addfix` 按 `pos+4` 算 → 位移偏 4 字节。
    实测：`__alloc` 释放自旋锁的那条写到了 bss+12（该 bss+8），锁永不释放，
    第二次分配直接自旋死锁。**写 `[rip+disp], imm` 时改成 `mov reg,imm; mov [rip+disp],reg`。**
35. **bump 分配器必须线程安全**（v2.34）：函数体是多线程并行编译的，每个线程
    开头都要 `_new_fc`（十几个 vec）。游标"读-加-写"不加锁就是丢更新 → 两个
    线程拿到同一块内存。**竞态指纹：同一输入每次报不同的错**（实测 -j2 报
    `未定义变量 pos`、-j4 报 `不支持的表达式节点 60`）。修法：`__alloc` 加
    `xchg [bss+8], r8` 自旋锁（xchg 带内存操作数隐含 lock）。

36. **工作区（arena）要按实际需要开，别"给足"**（v2.35）：`ARENA_CAP` 是从**堆**里
    `mem_alloc` 的，而堆大小就是 `BSS_SIZE`。16 MB 的 arena 让 stage-2 编自己时
    堆游标冲到 **31.7 MB / 32 MB**（耗尽 → AV，而且崩点随源码改动而移动，看着像
    "布局敏感"，其实是内存耗尽）。qlmc 自己产物的 .text 只有 440 KB，**4 MB 足够**。
    判断手段：`mem_alloc(0)` 返回当前游标，打出来看趋势。
37. **堆越界检查的上限要按「堆起点」算**（v2.35）：堆起点是 `bss+16`，写成
    `BSS_SIZE-64`（按 `bss+0` 算）会让上限比 .bss 末尾**还高 184 KB**，检查形同虚设。
    正确写法：`heap_start + (BSS_SIZE - 4096)`。

38. **`49 B9` 是 `mov r9, imm64`**（v2.40）：用 `_w32` 写立即数只会写 4 字节，后面的
    指令全被吃掉。现象是"看起来执行了，结果是把中间值原样打出来"。凡是用 `_w64` 的
    指令（`49 B8`..`49 BF` 的 mov r64,imm64、`48 B8` 的 mov rax,imm64）都必须 `_w64`。
39. **寄存器编号 ≥ 8 时逐位检查 REX**（v2.40）：手写机器码最容易漏的是 REX.R（目的
    寄存器）和 REX.X（SIB 索引）。`lea r9, [rcx+r10±k]` 要 `REX = W|R|X`（0x4E）；
    `mov byte [rcx+r10], imm` 要 `REX.X`（0x42）。漏了不报错，只是目的寄存器悄悄变成
    rcx、索引悄悄变成 rdx —— 只能靠反汇编核对。

40. **parser 分支别插错函数**（v2.23）：`_primary`（表达式）和 `_stmt`（语句）里都有
    `K_MATCH` 分支，拿它当锚点插入新关键字时很容易落到错的那个——`defer` 就曾插进
    `_primary`，于是 `defer x = x + 1` 变成"表达式语句包着一个 S_DEFER"。插完 `grep -n`
    确认一下分支在哪个函数里。
41. **类型编码按区间判定时区间不能重叠**（v2.22）：`TY_SLICE(0x20000)` 落在
    `TY_VEC(0x8000)..TY_ARRAY(0x100000)` 里，于是"是不是 vec 下标"的判断先把切片
    抓走了（把 `ptr` 当长度）。新增类型码前先画一遍区间，并把各分支的上界收窄。
42. **跨循环回边 / 跨调用的临时值必须 pin**（v2.17 踩过死循环，v2.21 踩过 AV）：
    临时值的活跃区间不覆盖回边，分配器会把槽位复用掉；`__alloc` 还会踩 R8。
    用 `_pin(fc, v)` 把值钉进变量再进循环/调用。
43. **帧 > 4 KB 的函数必须做栈探测**（v2.19 修，见 §7.17）：只发 `sub rsp, frame`
    会跨过 guard page，Windows 不扩栈，函数体第一次写帧就 AV——表现为"随机崩在
    某个 call"。stage-0 已按 `__chkstk` 的方式**自高向低**逐页 touch。
44. **`for` 的上界必须钉进变量**：临时值的活跃区间不跨循环回边（线性扫描的固有限制），
    上界留在临时值里，第二轮比较就会读到被别的临时值覆盖的寄存器——v2.17 实测是
    `for k in 0..3` 死循环。隐藏变量 `_new_var(fc, -1, …)` 是标准做法。
45. **别写"条件重赋值 + 跨 join 使用"**（v2.43 踩过，见 §7.27）：在 qlmc 自己的源码里
    写 `let mut s = f(); if c { s = g() }; use(s)`，分配器会把这两次定义当成同一个
    变量的前后两个定义（`let` 那条 `MOV dst, t` 被 coalesce 掉），跳过 if 的那条路上
    读到的是**未初始化的帧槽**。现象是 `jne lhave` 之后直接读 `[rbp-0x98]`（还是 0），
    于是 `[0]` 段错误。修法：两条路各写一次、各用一个只定义一次的变量（抽成小函数），
    或者用 `_pin` 出来的变量（固定帧槽，`_map_slot_of` 的 `lfull` 分支就是这么写的）。
    **排查手法**：`tools/dev/fault_probe.py` 拿 RVA → 把整个 `.text` 线性反汇编（capstone
    在 managed python 里有）→ 对着 RVA 找指令，比猜快得多。

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
| `tests/*.qma` | 150 个正向夹具，多数用 `assert` 自校验（v2.13 口径；含 `t130_router_dispatch` / `t132_timer` / `t140_net6` / `t141_vecindex` / `t142_exitcode`） |
| `tests/bad/*.qma` | 68 个负向夹具，**必须编译失败**（v2.12 新增 `net_serve_builtin`：reactor 搬进 std 后直接调内建 `net_serve` 必须给出迁移诊断） |
| `examples/*.qma` | 19 个可运行示例 |
| `bench/*.qma` | 32 个基准（v2.10 `http_router_bench`；v2.12 新增 `echo_bench`（无日志的 reactor echo 服务端）与 `net_cpu_bench`（handler 烧固定 CPU，用于多核标定）） |
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
| `tests/kv_test.py` | **KV 进程级恢复**：跨进程重开、撕裂尾（砍半条记录）、垃圾尾（追加 200 B）、Python 独立解析器逐条对拍磁盘格式 + FNV-1a 64 标准向量 | Windows |
| `tests/qla_test.py` | **`.qla` 目标文件**（v2.11）：往返逐字节（直编 vs 档案→链接）、函数级增量四种形态（无改动/改小函数/改大函数/加函数/改布局）、二进制库无源码链接、7 条失败路径、CLI | Windows |
| `tests/qlmc_test.py` | **stage-1 编译器差分**（v2.14）：先用 stage-0 编出 `bootstrap/qlmc/qlmc.qma`，再对 3 组用例分别用两个编译器编，比较 stdout 与退出码**逐字节相同** + 产物 PE 结构（PE32+/AMD64/节数）；`--time` 追加两侧编译墙钟 | Windows |
| `tests/http_router_test.py` | **HTTP 服务端路由 / 中间件端到端**：编译并启动 `examples/http_router.qma`，真实 socket 断言 20 项（命中 / 归一化 / 404 / 405 / 鉴权中间件 / 请求体 / gzip 协商 / keep-alive / 流水线）；`--bench` 追加吞吐与服务端 CPU | Windows |
| `tools/dev/net_bench.py` | **服务端网络探针**（v2.12）：echo / http / cpu 三种模式，`--conns`/`--reqs`/`--threads`，报告 req/s 与 RTT p50/p99（min-of-reps）；服务端由调用方先起（手动） | 全平台 |
| `tools/dev/incr_bench.py` | 增量/并行编译性能探针（单单元冷/热、多源 `-j`、`test -j`、进程创建基线，手动） | 全平台 |
| `tools/dev/qla_bench.py` | `.qla` 性能探针（冷编译 / 无改动增量 / 改一个函数 / link，附"解析占增量下限"的分离测量，手动） | 全平台 |
| `tools/dev/link_bench.py` | 链接期性能探针（import 合并 + 限定引用 + per-module mangling 三档同规模对照，手动） | 全平台 |
| `tools/dev/selfhost_status.py` | 自举进度：组件数与行数占比（`06-status.md` §4 的口径来源） | 全平台 |
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
| `tools/dev/check_bad.py` | **v2.32**：`tests/bad/` 里每个文件都必须**编不过**。负向用例的价值全在"它失败"上——特性一旦落地（v1.96 的 enum 派生 / f64 派生 / 运行时反射），原本该失败的用例就变成"能编过"，而主回归只跑名单里的用例，**不会有任何东西变红**。这个门禁把整目录扫一遍（并行，约 36 s），列出失效清单 |
| `tools/dev/fault_probe.py` | **v2.19**：让 exe 在调试器下跑，捕获访问违例并打印 RIP/RSP/RBP、AV 地址、rbp 链（支持 `PROBE_TRIES=n` 重试，因为这类崩溃常常是间歇的） |
| `tools/dev/frame_scan.py` | **v2.19**：扫 PE 里所有函数的帧大小（`push rbp; mov rbp,rsp; sub rsp,N`），报出 ≥ 阈值的——帧 > 4 KB 必须做栈探测，见 §7.17 |
| `quelmara doc std --missing` + `gen_stdlib_doc.py --check --require-doc` | 公开 API 面缺 `///` 文档、doc 块脱离、`03-stdlib.md` 与源码漂移 |

```bash
python tools/dev/check_names.py
python tools/dev/check_origin.py
python tools/dev/check_docs.py
python tools/dev/check_bad.py      # 负向用例必须仍然编不过（约 36 s，不放进主回归）
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
