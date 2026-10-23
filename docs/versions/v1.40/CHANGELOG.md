# v1.40 — 窄值存储截断全覆盖（整数宽度行收窄到只剩槽宽压缩）

- 日期：2026-10-23
- 任务：语言层 §1 整数宽度 🟡 收窄。v1.8 在 let 标注 / 形参 / 返回值 / 赋值边界
  截断；本版补齐**剩余全部存储点**：struct 窄字段、enum 窄载荷、vec 窄元素、
  定长数组窄元素。截断后"二进制格式要自己 mask"不再成立。
- 影响面：编译器（原生后端 5 处存储路径 + 数组窄元素跟踪）、测试（t85）、文档

## 为什么是它

v1.39 收尾时 §8 顺序进入"黄标逐项"。上一轮已把 `narrow_of` / `trunc_to`
基础设施和四处截断（struct 字段字面量/枚举载荷/vec push/vec set）落了大半
未提交；本轮补上字段赋值复合形态之外的缺口——**定长数组**（此前元素类型
只跟踪 f64 位模式，窄元素下标赋值/整体赋值/形参拷贝全部不截断），并把
未提交的四处一起验证收口。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `lower_struct_lit`：窄字段字面量截断 |
| `tools/stage0/qlm_native.py` | enumlit 窄载荷截断 |
| `tools/stage0/qlm_native.py` | `vec.push` / `vec.set`：`vec[u8]` 等窄元素截断 |
| `tools/stage0/qlm_native.py` | 字段赋值 `p.f =` / `p.f +=`：窄字段截断 |
| `tools/stage0/qlm_native.py` | **数组窄元素跟踪**（本轮新增）：`arr_narrow`（base vreg -> (bits, signed)）；`array_copy` 加 `nb` 参数；let 标注数组字面量**就地逐元素截断**；数组整体赋值按目标声明宽度拷入截断；`a[i] =` / `a[i] +=` 存槽截断；数组形参入口拷贝截断 |
| `tests/t85_narrowstore.qma` | **新增**：20 条断言（struct 字段/enum 载荷/vec 元素/数组字面量/下标赋值/复合下标/整体赋值拷入/形参入口/标量纪律复核） |
| `tests/run_win_tests.py` | 注册 t85（主回归 147 → 148） |
| `tools/stage0/qlm_cli.py` | VERSION 1.39.0 → **1.40.0** |
| `docs/02-language.md` | §8.1 边界表补 4 行存储点；边界如实登记（vec[u8] 槽仍 8 字节、切片别名写入不截断） |
| `docs/07-gaps.md` | §1 整数宽度行收窄（语义全覆盖，剩槽宽压缩）；§8 推进顺序同步 |
| `docs/06-status.md` | 回归 148 / lexdiff 133 / parsediff 117 / bodydiff 1172-872 / irdiff SKIP 47 |

## 实现要点

- **截断只发生在存储边界**：表达式内部仍按 64 位提升（`u8 200 + 100 == 300`），
  与 v1.8 语义一致；`trunc` 指令只在窄类型存储点发射，**非窄程序代码生成零变化**。
- **数组窄元素靠声明侧跟踪**：数组值本身只是帧槽地址，元素类型此前只对 f64
  位模式跟踪（`arr_elem`）。窄宽度加平行表 `arr_narrow`，在四个"声明可见"
  的点登记：let 标注直接绑定（字面量）、let 标注拷贝、数组整体赋值目标、
  数组形参。消费点两处：下标赋值（= 与 +=）与拷入。
- **字面量就地截断**：`let a: [3]u8 = [300, 1, 258]` 字面量直接绑定不拷贝
  （v0.6 优化），所以对已存槽的元素逐个 load→trunc→store，不改绑定路径。
- **fail-fast 纪律不变**：A64 遇 `trunc` 形态编译期报错（`irdiff` SKIP=47 如实
  登记，与 t49 同类）；切片别名写入不截断（切片元素只跟踪 str），写进文档边界。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=148 FAIL=0 SKIP=1**（v1.39 为 147；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t85_narrowstore.qma --target win` | ok（20 条断言全过） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 133 / 117 全绿 |
| `python tests/bodydiff.py` | 一致 1172 / 分叉 872 / SKIP 24-18（t85 函数体 stage-1 尚未支持窄宽度形态，如实分叉） |
| `python tests/irdiff.py` / `emitdiff.py` | 66-0-47 / 10-0 |
| 性能（改动前 = git worktree@HEAD(v1.39) 基线，改动后各跑两遍） | 见下——**无回退** |

性能对照（基线 → 改动后，两轮取代表；VBS 噪声带 ±50%）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 41 / 10 / 76 / 2 ms | 41 / 9 / 74 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.86 / 47.7 / 4.19 / 39.7 ms | 3.83 / 47.6 / 3.99 / 39.5 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.75 / 2.01 / 0.35 / 49.9 ms | 0.72 / 1.77 / 0.33 / 49.7 ms |
| bench_str scan16k / concat20k / loopsum50m / collatz | 224 µs / 79.4 / 76.6 / 102.4 ms | 224 µs / 81.5 / 79.5 / 104.8 ms |

首轮 map_str 5.05 ms / nested 0.40 ms 的波动复跑即回落（3.99 / 0.33），
属 VBS 已知噪声。改动只新增窄类型存储点的 `trunc` 指令，非窄程序生成代码
逐字节不变——与实测一致。

## 已知边界 / 遗留

- **`vec[u8]` 元素槽仍是 8 字节**：语义已对（存取都截断），只是内存不压缩。
  槽宽压缩要动 vec 运行时的字寻址假设（esz 字节寻址化），属独立的性能/内存
  专项，整数宽度行保持 🟡 只为这一项。
- **切片别名写入不截断**：`slice_of(a)` 后 `s[i] = 300` 绕过数组窄宽度
  （切片元素类型只跟踪 str）。要堵需把窄元素标签带进 slice 标记，与
  `slice_elem` 现有 str 标记同构，留作下一轮小补。
- **A64 后端未接 `trunc`**：编译期明确报错（irdiff SKIP 如实登记），
  与 chan/map/spawn 等同属 arm64 待接入清单。
