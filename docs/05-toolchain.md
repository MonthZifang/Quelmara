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
| `version` | 版本与能力 | — |

`--target` 取值：`native`（ELF64）/ `win`（PE32+）/ `arm64`（AArch64 ELF）/ `c`（C99，仅交叉验证）。

```bash
python tools/stage0/qlm_cli.py run examples/hello.qma --target win
python tools/stage0/qlm_cli.py test tests/selftest.qma --targets all
python tools/stage0/qlm_cli.py build examples/loop_sum.qma --target win -o build/ls.exe
python tools/stage0/qlm_cli.py bench bench/p0_bench.qma --runs 5
```

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

依赖写在项目 `Quelmara.toml`：

```toml
[deps]
mylib = "path:../mylib"                  # 本地路径
other = "git:https://github.com/u/r#v1"  # git + 可选 rev
```

- git 依赖 clone 到 `~/.qpm/cache`，再复制到 `<project>/.qpm/deps`（Windows 无 symlink，
  复制保证离线可构建）。
- 锁文件 `.qpm/lock.toml` 记录来源与 sha。
- 约定：**git 仓库根 = 包根**；包名必须 import-safe（用下划线，连字符不是合法标识符）。
- 未做：semver 区间、registry、发布流程、传递依赖冲突合并。

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
| `tools/dev/tls_probe.py` | 真实服务器 TLS 1.3 握手探针（Python 提供 socket，手动运行） | 全平台（需网络） |
| `tests/a64_emu.py` | AArch64 指令模拟器 | 全平台 |

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
  （注意：该命令当前打印的是 `1.0.0`，与文档版本线不一致，见 `07-gaps.md`）。
