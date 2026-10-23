# v1.47 — std/math 超越函数：exp / log / pow / 三角 / 反三角 / 双曲（标准库）

- 日期：2026-10-23
- 任务：标准库轨第一轮（用户分轨：语言层归另一会话，工具链已有其线，标准库归本轨）——
  07-gaps §2「数学」行翻绿：补 `exp` / `log` / `log2` / `log10` / `pow(x,y)` /
  `sin` / `cos` / `tan` / `asin` / `acos` / `atan` / `atan2` / `sinh` / `cosh` /
  `tanh` / `hypot` + 常数助手（pi/e/ln2/ln10/sqrt2/nan/inf）。
- 影响面：`std/math.qma`、`tests/t90_mathfn.qma`（新增）、`tests/run_win_tests.py`
  （注册）、`docs/03-stdlib.md`（重生成）、`docs/06-status.md`（PASS=155→156）、
  `docs/07-gaps.md`（§2 数学行 + 新登记 `__f64_to_str` 运行库缺陷）、
  `tools/stage0/qlm_cli.py`（VERSION 1.45.0 → 1.47.0）

## 为什么是它

HANDOFF §8.4 把标准库第一顺位留给数学（"exp/log/sin/cos"）；v1.19 的
`std/math.qma` 头部自记"没有 exp/log/pow(x,y)：需要自然对数，登记在
docs/07-gaps.md"——本轮清账。选它开轨的理由：纯计算、零 I/O 依赖、与语言轨
（defer 在途）和工具链轨（doc comment  rollout 在途）零文件重叠；精度可对拍
Python math 库逐点验证。

版本号取 v1.47：v1.46 原预留给语言轨在途的 defer，但本轨先落地造成撞号，
defer 顺延为 v1.48（v1.46 空号）；三轨共享连续版本号，后到者重编。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/math.qma` | 新增「超越函数」节（约 480 行）：常数助手 + exp/log/log2/log10/pow + sin/cos/tan + asin/acos/atan/atan2 + sinh/cosh/tanh + hypot/to_radians/to_degrees；内部助手 `_floor_int` / `_mod4` / `_sin_core` / `_cos_core` / `_atan_unit`。每个 pub fn 带 `///` 文档注释（qlm_doc 直出 03-stdlib） |
| `tests/t90_mathfn.qma` | **新增**：148 条断言——算法精度对拍 Python math（exp/log/pow/atan 系 eps 1e-12，sin/cos/tan 大角度 eps 1e-9）、精确路径（整数幂 / 0 与 1 的特殊值）、特殊值（NaN/inf）、溢出边界（exp(710)=inf、exp(-746)=0、sinh(710)/cosh(710) 有限） |
| `tests/run_win_tests.py` | 注册 `case_selfcheck("t90_mathfn", ...)` |
| `docs/03-stdlib.md` | 重生成（gen_stdlib_doc.py）。**顺带修复 v1.45 遗留的文档漂移**：qlm_doc 扫描器改成认 `pub fn` 后未重新生成，库里一直显示 195 个"公开函数"（实为把内部函数误列）；现为 296 个公开函数口径 |
| `docs/06-status.md` | 主回归 PASS=155 → PASS=156 |
| `docs/07-gaps.md` | §2 数学行 ✅ v1.47；§2 编码行新登记 `__f64_to_str` 运行库缺陷（根因已定位，见下） |
| `tools/stage0/qlm_cli.py` | VERSION 1.45.0 → 1.47.0 |

## 实现要点

- **exp**：x = n·ln2 + r（Cody–Waite 双字常数 ln2_hi/lo），n 截到
  [-1074, 1023]（2^n 可表示范围）后余量并入 r；exp(r) 走 17 项 Taylor
  （|r| < 0.93 时截断 < 1e-16）；再按 2^n 缩放——2 的幂缩放在 IEEE 下精确。
- **log**：x = m·2^e（m ∈ [√½, √2)），s = (m-1)/(m+1)（|s| ≤ 0.1716），
  ln(m) = 2s·Σ z^k/(2k+1)（z = s²，11 项）；e·ln2 拆双字累加。
- **sin/cos**：k = round(x/(π/2))，r = x − k·(π/2)_hi − k·(π/2)_lo（|r| ≤ π/4），
  象限查表 + 9 项 Taylor。|x| ≥ 2^52 时 ULP 超过 π/2、无法定相 → 断言失败
  （fail-fast，不静默返回垃圾）。
- **atan**：半角公式 atan(x) = 2·atan(x/(1+√(1+x²)))（参数 ≤ tan(π/8)），
  21 项交错级数；asin/acos 由 atan + 补角恒等式导出（端点附近避开 1-x² 相减抵消）。
- **sinh/cosh**：|x| > 20 走 exp(|x|−ln2)，避开 e^x 中间溢出——
  sinh(710) = 1.117e308 是有限值，(e^710 − e^-710)/2 会错误地给 inf。
- **pow**：整数指数（|y| < 2^63）走 powi 精确快速幂（含负底奇次幂）；
  否则 exp(y·log(x))；0/负底/无穷组合按 C 库约定。
- **方法论**：落码前先用 Python 逐行镜像同一算法（同常数、同项数、同顺序），
  对拍 math 库 6000+ 随机向量 + 边界。镜像抓出三个设计 bug 后再落 Quelmara：
  ① atan 漏了半角公式的 ×2（系 0.39 的系统误差）；
  ② log 级数系数写成 1/(2k+3)——恒定项变成 1/3（log(e) 偏 0.2）；
  ③ sinh(710) 中间溢出。t90 一次通过。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t90_mathfn.qma --target win` | PASS（148 断言） |
| `python tests/run_win_tests.py` | PASS=156 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，本机被沙箱拦） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（重生成后） |

> 回归实测备注：本轮跑回归时工作区同时带着语言轨在途的 t91_defer / defer_let
> 负例（两者同场全过），当时合计 PASS=158；上表 156 = 本轨净增（t90）后的
> 本 commit 口径（干净检出下语言轨文件尚不存在）。语言轨提交后各自口径自然分开。

## 已知边界 / 遗留

- **sin/cos/tan 大角度**：归约误差随 |x|·1.1e-16 线性增长（k·(π/2)_hi 的
  乘法舍入，纯 double 的固有限制）——|x| ≤ 1e3 时 ≤ 6e-14，1e6 时 ≤ 5e-11；
  要 glibc 级精度需多字 π 归约（Payne–Hanek），登记 07-gaps §2。
- **log2/log10 是 log 的倍数**（非独立算法），未对 2 的幂做精确捷径。
- **`__f64_to_str` 运行库缺陷**（本轮实测发现，属语言层/运行库，不在标准库轨）：
  `print(f64)` / `x.to_str()` 对有限非零值输出空串（len=0）；nan/inf/±0 正常。
  根因：`qlm_native.py` 的 `__f64_to_str` 有限路径（定点与科学计数）收尾时直接
  `ret(buf)`，漏写长度前缀且未返回 `buf+8`——对照同函数内 `ret_buf()` 的写法；
  C 后端 `qlm.py: qlm_f64_to_str` 有独立实现（双链 diff 依赖），修时两边对拍。
  已登记 07-gaps §2 编码行。**该缺陷使浮点无法打印，建议语言轨优先修。**
- exp 在 x ∈ (709.8, 710.47] 区间依赖自然溢出判定，±1 ulp 边界未逐点校准。
- 版本号：defer 顺延为 v1.48（v1.46 空号）；本轨下一轮（HTTP 客户端或 f64 格式化
  之外的标准库项）接 v1.49。
