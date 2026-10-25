# v2.54 — 基准搬到 GitHub Actions；`run.py` 与 C 侧跨平台化

- 日期：2026-10-25
- 任务：基准改用 CI 采集（低噪声 + 多平台 + 适配度）；顺带把基准套件跨平台化
- 影响面：`.github/workflows/bench.yml`（新增）/ `bench/speed/run.py` /
  `bench/speed/c/`（10 个文件 + 新增 `bench.h`）/ 文档

## 为什么必须搬走

本机开着 VBS（虚拟化安全），实测噪声已经大到**单次测量没有意义**：

| 现象 | 数字 |
|---|---|
| 进程创建（四个语言的空程序都一样） | **447 ms** |
| `b1_int` 单次跑 / min-of-5 | **59.3 / 42.4 ms**（差 40%） |
| 4 线程加速比，同一份代码三轮 | **3.06× / 3.22× / 3.85×** |

过去九轮的结论里，"−3%""−5%"这种量级的判断在本机**根本立不住**。所以：

- **本机只做"改完有没有明显变慢"的粗判**；
- **对外引用的数字一律来自 CI**（干净 runner，噪声低一个量级）。

## 新增 `.github/workflows/bench.yml`

三个触发口：手动（可指定 `reps`）、推到 master 且动了
`bench/**` / `bootstrap/qlmc/**` / `tools/stage0/**`、每周一 02:00（UTC+8）。
结果同时写到 **job summary**（人看）和 **artifact**（机器读，留 90 天）。

| job | runner | 跑什么 | 能回答什么 |
|---|---|---|---|
| `windows` | `windows-latest` | 四语言全量 + 编译器轴 | **qlmc 对 C/Go 的真实比值** |
| `posix` | `ubuntu-latest` + `macos-latest` | C / Go / Python | 同一道题在别的平台上的样子 = **适配度** |

Windows 上的 C 编译器用 **zig**（runner 只有 MSVC，没有 gcc/clang；zig 是单文件
免安装，`zig cc -O2` 就是 clang）。qlmc 用 stage-0 自举出来。

## 为了能跨平台，改了三处

**① `c/bench.h`（新增）—— 计时抽象。** 原来 10 个 `.c` 各自内联一份
`QueryPerformanceCounter` 宏，想加 POSIX 支持要改 10 处。抽成一个头文件：

```c
#ifdef _WIN32
  #include <windows.h>            // QPC
#else
  #include <time.h>               // CLOCK_MONOTONIC
#endif
```

**② `b8_threads4.c` —— 线程两条路径。** `CreateThread` / `pthread_create`，
但**同一道题、同一种线程模型**（4 个可 join 的 OS 线程，无池无复用），
否则跨平台就没法比。

**③ `run.py` —— 平台判定。**
`IS_WIN` / `EXE`（产物后缀）、`ctypes.wintypes` 与 `psapi` 峰值内存只在 Windows
导入、`p._handle` 只在 Windows 读。qlmc 在非 Windows 上给一句明确的跳过理由
（"只有 Windows PE 后端"），而不是含混的"文件不存在"。

## 一个必须说清楚的事实

**qlmc 只有 Windows PE 后端**，所以 posix 那两行**没有 quelmara 列**。
这不是"跑不过"，是"还没有产物"。等 `--target elf` 落地，把 `run.py` 里那句
跳过去掉就行 —— **那一刻"跨平台适配度"这一列才真正有意义**。

我在 `README.md` 和 `RESULTS.md` 顶部都写明了这件事，免得以后有人拿
"posix 没有 qlmc"当成回归。

## 第一次 CI 跑出来的结果（run 40221645429）

三个 job 全绿：`windows` 7m54s、`posix (ubuntu)` 3m4s、`posix (macos)` 4m5s。
**40 个校验和全部一致。**

`windows-latest`、`--reps 5`：

| 基准 | Quelmara | C | Go | Python | qlmc / C |
|---|---|---|---|---|---|
| `b1_int` | 28.4 | **6.4** | 19.1 | 2890.4 | 4.4× |
| `b2_float` | 59.5 | **7.0** | 6.9 | 747.9 | **8.5×** |
| `b3_recursion` | 7.9 | **2.4** | 4.2 | 133.9 | 3.3× |
| `b4_array` | 11.1 | 3.6 | **3.5** | 565.8 | 3.1× |
| `b5_string` | **29.7** | 39.9 | 20.9 | 203.2 | **0.74×** |
| `b6_hash` | **10.5** | 11.0 | 11.1 | 310.0 | **0.95×** |
| `b7_sort` | 21.4 | **13.2** | 13.2 | 421.3 | 1.6× |
| `b8_threads1` | 226.5 | **50.9** | 151.9 | 15012.5 | 4.5× |
| `b8_threads4` | 115.7 | **69.0** | 89.3 | 14398.7 | 1.7× |
| `b9_json` | 20.6 | **5.1** | 5.4 | 949.8 | 4.0× |

**最重要的一条：qlmc 已经有两项快于 C** —— `b5_string` **0.74×**（快 34%）、
`b6_hash` **0.95×**。这不是"接近"，是**已经赢了**。`b7_sort` 1.6× 也进了同一档。

本机（VBS 噪声下）测出来 `b5_string` 是 1.4× **慢于** C，CI 上却是 1.34× **快于** C ——
**噪声足以把结论反过来**。这就是必须搬走的原因。

### 顺带发现：CI 从 v2.48 起一直是红的

推完 v2.54 顺手看了下 CI 状态，发现 `ci` 从 v2.48 起**每一次都失败**（21 秒就红）。
不是这几轮的编译器改动，是两个**环境假设**问题：

1. **`UnicodeEncodeError: 'charmap' codec can't encode characters`** ——
   runner 默认不是 UTF-8（Windows 是 cp1252），而仓库里到处是中文输出。
   linux / windows / perf 三个 job 全部在第一步就炸。
   修法：`ci.yml` 加 workflow 级 `env: { PYTHONIOENCODING: utf-8, PYTHONUTF8: "1" }`
   （新的 `bench.yml` 一开始就设了这两个，所以它没踩）。
2. **`PermissionError: [Errno 13] ... chain.exe`（Linux）** ——
   `qpm_test.py` 跑刚生成的产物，POSIX 上刚写出来的文件没有执行位。
   修法：执行前 `os.chmod(out_exe, 0o755)`（仅非 Windows）。

这两个都是"环境假设"问题，但它们让 CI 长期处于红的状态 —— **等于 CI 完全没起作用**。

### 跨平台反直觉的两点

- **`b1_int` 上 C 与 Go 的胜负会翻转**：ubuntu 上 Go 快（14.6 vs 19.0），
  macOS 上 C 快 3.3 倍（6.1 vs 20.2）。同一份源码、同一个 `-O2` ——
  差别在目标 CPU 与后端。**"某语言比另一个快"离开平台就没有意义。**
- **`b8_threads1` 跨平台方差 4 倍**（C：50.9 / 116.2 / 205.8）。
  单线程纯算术不该这样 —— 更可能是 runner 的 CPU 型号与降频策略。
  所以 workflow 里加了"机器信息"步骤，数字必须带机器读。

## 验证

| 项 | 结果 |
|---|---|
| `yaml.safe_load` 解析 workflow | **OK**（2 个 job，9 / 6 个 step） |
| 10 个 `.c` 在 Windows 下用 `zig cc -O2` | **10/10 编译通过** |
| `run.py --langs c go python --markdown` | 正常出表（无 quelmara 列） |
| `run.py --reps 1` 全量 | **40 个校验和一致** |
| `run.py` 语法 / 本地四语言跑通 | OK |

## 改动

| 文件 | 改了什么 |
|---|---|
| `.github/workflows/bench.yml` | **新增**：windows 全量 + posix 参照 |
| `bench/speed/c/bench.h` | **新增**：QPC / `CLOCK_MONOTONIC` 计时抽象 + 线程句柄类型 |
| `bench/speed/c/b*.c` | 10 个文件改用 `bench.h`；`b9_json.c` 的局部 QPC 段改宏；`b8_threads4.c` 加 pthread 路径 |
| `bench/speed/run.py` | `IS_WIN`/`EXE`、ctypes 与 psapi 守卫、qlmc 跳过理由 |
| `bench/speed/README.md` | 新增「在 CI 里跑」一节（触发方式、为什么本机不准、平台矩阵） |
| `bench/speed/RESULTS.md` | 新增「一、CI 数字（权威）」+ 三平台对照；本机表降级成「二、参照」 |
| `.github/workflows/ci.yml` | **修**：workflow 级加 UTF-8 env（否则中文输出在 runner 上直接炸） |
| `tests/qpm_test.py` | **修**：POSIX 上跑产物前 `chmod 0o755`（Linux CI 一直红的第二个原因） |

## 下一步（CI 跑出第一批数字之后）

有了干净数字，剩下三件事的优先级就能定死：

1. **内联器** —— `b9_json` 的主要差距是函数调用开销（每 token 一次，
   prologue + epilogue 约 14 条指令）。这是**唯一**能让 `b9_json` 从 3.9× 掉到
   2× 以内的东西。
2. **XMM 寄存器文件** —— `b2_float` 2.9×，f64 现在每次运算两次 `movsd` 内存往返。
3. **范围分析** —— 彻底去掉每字节的越界检查（`b9_json` / `b7_sort`）。

`b4_array`（3.8×）是内存带宽，不在编译器能改的范围里。
