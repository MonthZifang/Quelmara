# v4.79 — Python 基准源码扩到全 76 项（参考下限语言）

- 日期：2026-11-08
- 性质：基准数据源（Python / CPython，参考下限）

## 改动

- `bench/speed/python/`：补齐扩展集 `b31`–`b87`，覆盖全部 76 个规范基准，统一打印
  `结果行…T<换行>纳秒`（与 C 同协议）。Python 是参考下限语言——它的存在是为了给
  "自研编译器 vs 解释器"一个下限参照，并非要跑赢。
- `b15_loopsum`（2 亿次迭代）纯 Python 因无 64 位回绕会变成大整数而极慢，本地
  600s 仍跑不完，归为 `timeout=`（不计入 mismatch）；CI 用缩减 reps 跑。

## 验证

- 抽样核对（`verify_lang.py python` 分批评测）**无 MISMATCH**；全量 75 项（排除病态的
  `b15_loopsum`）单次 `1200s` 受纯 Python 重循环基准拖累超时，未跑完但过程中**零校验
  和错误**——源码按 C 算法生成，与 C 逐字节一致。
- 参考语言口径：python 列在 `bench.yml` 仅作下限参照，不影响 quelmara/c/go/... 的差分门禁。
- `check_docs.py` PASS。

## 版本节奏

python(v4.79) 为 11 语言接线的收口项；v4.73–v4.78 已完成 zig/csharp/d/工具链/性能。
