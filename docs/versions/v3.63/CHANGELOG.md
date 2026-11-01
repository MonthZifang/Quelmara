# v3.63 — 覆盖率口径修正：分母排除平台专用模块；工具可在 Linux 上跑

- 日期：2026-11-01
- 任务：用户要求"继续"。v3.62 之后剩 3 个模块，本版先逐个核实它们的
  **真实**阻塞点 —— 结果发现其中一个是**度量错误**，不是 qlmc 的缺口。
- 影响面：`tools/dev/qlmc_coverage.py`（平台专用排除表 + 自检 + wine 支持）
- 代码改动：**零**（qlmc 本身没动）
- 覆盖率：**67/70 → 67/69**（数字没涨，口径变准）

## 核实：三个模块里有一个根本不该算

| 模块 | stage-0 能编 win？ | qlmc 能编？ | 判定 |
|---|---|---|---|
| `std/csv` | ✅ 能 | ❌ 不能 | **真缺口**（`vec[vec[T]]`） |
| `std/gen` | ✅ 能 | ❌ 不能 | **真缺口**（泛型） |
| `std/park_linux` | ❌ **也不能** | ❌ 不能 | **度量错误** |

`std/park_linux` 用 `syscall(...)`，而 `syscall` 只在 Linux/arm64 后端
存在 —— 在 Windows 目标上是**声明期硬失败**。实测 stage-0：

```
$ python tools/stage0/qlm_cli.py build std/park_linux.qma --target win --lib -o /tmp/pl.exe
[qlm] 编译错误：syscall() 只在 Linux（native / arm64）后端实现
```

**它不是"qlmc 的缺口"，是"这个模块本来就不产出 Windows 产物"。**
把它放进分母，等于让覆盖率上限永远被钉在 69/70 —— 那个分母里有一个
**不可能项**。

全量核对过：`std/**/*.qma` 里 stage-0 在 win 目标上编不过的**只有它一个**，
所以这个排除是有界且可验证的，不是"挑着排除"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/dev/qlmc_coverage.py` | 新增 `PLATFORM_SPECIFIC` 表 + `_verify_platform_exclusions()` 自检；`_exe_runner()` 支持 Linux/wine |

### 关键：排除表**必须自检**，否则它就是垃圾桶

如果只写一张"这些模块不算"的表，下一个人迟早会往里塞
"qlmc 编不过但其实能编"的模块来刷数字。所以加了 `_verify_platform_exclusions()`：
**用同一条 stage-0 CLI 命令复核，编得过就报 FAIL 并退出**。

第一版自检写错过两次，都是**假绿**：

1. 用 `transpile_win()` 直接调 —— 它对 lib 模块抛 `KeyError: 'main'`，
   被 `except Exception` 吞掉，于是**任何**模块都被判成"编不过"。
   故意塞 `std/json.qma` 进去，自检照样返回 OK。
2. 改成"只认 `SyntaxError`"—— 仍然不对：`json` 抛的是 `KeyError`，
   落进"跳过"分支，还是判不了。

**最终判据**：直接用**和覆盖率工具完全相同的那条 CLI 命令**
（`build <mod> --target win --lib`），`returncode == 0` 就是"能编"。
这才和被测对象同口径。现在塞 `std/json.qma` 进去会正确报错：

```
bad: ['std/json.qma：stage-0 **能**编出 win 目标 —— 它不是平台专用，不该被排除（test）']
```

**教训：自检必须用"被测对象同一口径"的判据。**
用相近但不同的 API 复核，得到的绿灯是假的 —— 而且假得很难发现，
因为它平时一直是绿的（所有模块都"编不过"，全部符合预期）。

### 顺带：工具现在能在 Linux 上跑

原来 `subprocess.run([exe, ...])` 直接执行 PE，在 Linux 上靠
`binfmt_misc` 的 `MZ` handler —— 而那个 handler **会把 argv[0] 重复塞进去**，
qlmc 于是把 `build` 当成源文件名：

```
std/json.qma: qlmc: 打不开源文件 build
```

全部 70 个模块都报这个，覆盖率显示 `0 / 70`。新增 `_exe_runner()`：
Windows 直跑、Linux 显式走 `wine`。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/dev/qlmc_coverage.py` | **67 / 69 PASS**（排除表自检通过） |
| 自检反向验证（塞 `std/json.qma`） | **正确报 FAIL** |
| 全量核对 stage-0 在 win 的失败模块 | **只有 `std/park_linux` 一个** |
| 文档门禁（4 个） | 全 PASS |

## 剩余真实缺口：2 个

| 模块 | 缺口 | 难度 | 说明 |
|---|---|---|---|
| `std/csv` | `vec[vec[T]]` 类型码撞区间（§7.18） | **高** | 架构性：`TY_VEC=0x8000` 相加会撞 `TY_MAP=0x10000` |
| `std/gen` | 泛型 `[T: Ord]` | **高** | 需要单态化 |

两个都是"专门版本"级的架构工作。`std/gen` 的报错是
`期望标点 #1` —— 连泛型语法都没进 parser，属于**从零开始**。

## 这一版为什么值得单独提交

数字从 `67/70` 变成 `67/69`，**看起来什么都没做**。但：

* 之前任何"覆盖率提升"的报告里，分母都含一个不可能项 —— 也就是说
  **"67/70 = 95.7%"这个百分比本身是错的**，真实是 67/69 = 97.1%；
* 更重要的是：**排除表带了自检**。这是防止下一个人把这张表变成
  "刷数字的垃圾桶"的唯一机制。

> 一个不准确的度量，比没有度量更危险 —— 它会让人对错误的数字产生信心。
