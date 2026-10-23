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
| `build` | 编译 | `src`、`--target`、`-o/--out`、`--no-opt`、`--dump-ir` |
| `run` | 编译并运行 | `src`、`--target`、`--` 之后的参数传给程序 |
| `test` | 跑 `test "名字" { }` 块 | `paths`、`--target`、`--targets`（逗号分隔或 `all`）、`--no-opt` |
| `fmt` | 格式化 | `paths`、`--check`（只检查）、`-q/--quiet` |
| `lex` | 词法分析 | `src`、`--stage0`（默认优先用自举词法器） |
| `bench` | 基准 + 回归对比 | `src`、`--runs`（默认 5）、`--baseline`、`--update-baseline`、`--threshold`（默认 10%）、`--targets` |
| `debug` | 源码级调试器（v1.75） | `src`（.qma 自动带调试信息构建）或产物、`--script`（命令脚本）、`--` 之后传给程序 |
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
python tools/qpm.py install            # 按 [deps] 拉取依赖并写锁
python tools/qpm.py add <name> <spec>  # 添加依赖并 install
python tools/qpm.py remove <name>
python tools/qpm.py list
```

依赖写在项目 `Quelmara.toml` 的 `[deps]` 段，`name = "spec"`：

```toml
[deps]
mylib   = "path:../mylib"                      # 路径依赖（显式前缀）
other   = "git:https://github.com/u/r#v1.2.3"   # git + 精确 tag/branch/sha
newest  = "https://github.com/u/r#^1.2.0"       # git + semver 区间（选最新满足 tag）
```

- **spec 形态**（v1.45）：`path:` 前缀，或以 `./` `../` `/` 盘符开头 = 路径依赖；
  `git:` 前缀或裸 URL = git 依赖。`#` 之后是**精确 rev**（tag/branch/sha）或
  **semver 区间**——含运算符（`^ ~ > >= < <= = *`）、通配段（`1.2.x` / `1.*`）
  或分隔符（逗号/空格 = AND，`||` = OR）的按区间解析；纯版本串按精确 tag。
- **区间解析**（`tools/qpm_semver.py`，纯标准库）：`git ls-remote --tags` 列
  tag → 选满足区间的**最大**版本 → rev 收敛为具体 tag 后走 clone/缓存/复制。
  无满足 tag 时 **fail-fast** 并列出远端全部可用 tag。预发布版本默认不选中
  （`^1.2.3` 选不到 `2.0.0-rc1`；要预发布须显式写 `^1.2.3-rc1`）。区间语法
  与语义边界见该模块 docstring。
- git 依赖 clone 到 `~/.qpm/cache/<name>-<rev>`，再复制到
  `<project>/.qpm/deps/<name>/`（Windows 无 symlink，复制保证离线可构建）。
- 锁文件 `.qpm/lock.toml`：`name = "kind|src|rev|sha"` 四段式；区间依赖的
  rev 是**解析后**的 tag，区间文本留在 `Quelmara.toml`——两处对照即
  "声明 vs 锁定"。
- 约定：**git 仓库根 = 包根**；包名必须 import-safe（用下划线，连字符不是合法标识符）。
- 未做：registry、发布/上传流程、传递依赖冲突合并。

测试：`python tests/qpm_semver_test.py`（单测 + `file://` 本地 git 端到端；
`fixtures/qpm-demo` 的 `.git` 不入库，测试按需重建）。

端到端夹具：`fixtures/qpm-demo`（路径依赖 + `file://` git 依赖两条路）。

## 5. 测试体系

### 5.1 夹具

| 目录 | 内容 |
|---|---|
| `tests/*.qma` | 72 个正向夹具，多数用 `assert` 自校验 |
| `tests/bad/*.qma` | 12 个负向夹具，**必须编译失败** |
| `examples/*.qma` | 17 个可运行示例 |
| `bench/*.qma` | 8 个基准 |
| `fixtures/` | 端到端工程夹具（srcproj / qpm-demo） |

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
| `tests/debugger_test.py` | 调试器脚本化会话（18 项期望 + 调试/非调试构建输出逐字节相同） | Windows |
| `tests/dbg_test.py` | 调试器端到端命令链（断点/三种不可读语义/单步/bt/退出码） | Windows |
| `tests/dwarf_test.py` | DWARF v4 互操作：独立读取器解析四个节，逐项对照 `.qlmdbg` | 全平台 |
| `tools/dev/dbg_bench.py` | 调试链路性能探针（构建开销 / 体积占比 / 每命中 / 每步，手动） | Windows |

### 5.3 门禁（CI 双平台都跑）

| 脚本 | 拦什么 |
|---|---|
| `tools/dev/check_names.py` | 旧项目名残留、`.ros` 扩展名残留、C 运行时符号自洽 |  <!-- legacy-ok -->
| `tools/dev/check_origin.py` | 只用标准库、无异语言运行时特征、无第三方目录 |
| `tools/dev/check_docs.py` | 过期断言黑名单、文档索引完整性、版本目录完整性、数字单一来源、`VERSION` 与版本目录同源 |

```bash
python tools/dev/check_names.py
python tools/dev/check_origin.py
python tools/dev/check_docs.py
```

## 6. CI

`.github/workflows/ci.yml`，push 到 master 或 PR 触发，两个 job：

| job | 步骤 |
|---|---|
| `linux`（ubuntu） | 三道门禁 → 四套对拍（lex/parse/IR/emit）→ C 后端回归 → 自研 ELF 回归（含 A64 模拟器）→ 运行时回归（corelib + io_uring） |
| `windows` | 三道门禁 → PE 回归 → gzip 解码 / ECDSA / X.509 互操作 → 词法/声明级对拍 → `test --targets all` 多后端矩阵 |

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
```

## 8. 发布与推送

- 推送：`git push` 直连时通时断（本机代理会拦 `github.com:443` 的 CONNECT）；
  稳定通道是 `python tools/dev/push_via_api.py`（逐 blob 建 tree/commit 再 PATCH ref，
  凭据走 Windows Credential Manager）。
- 产物是单文件可执行程序，无运行时依赖；版本号口径见 `qlm_cli.py version`
  （与 `docs/versions/` 最新目录同源，由 `check_docs.py` 门禁强制）。
