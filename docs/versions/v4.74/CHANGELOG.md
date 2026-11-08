# v4.74 — 校验和门禁工具链：参考语言超时归为独立类别

- 日期：2026-11-08
- 性质：基准工具链（非数据源）

## 改动

- `tools/benchgen/verify_lang.py`：
  - Python 是参考下限语言，重循环基准天然慢（如 `b15_loopsum` 2 亿次迭代；纯 Python
    因无 64 位回绕会变成大整数而极慢）。将 Python 运行超时从 120s 提到 600s。
  - `run()` 捕获 `subprocess.TimeoutExpired` 返回 `"TIMEOUT"`，`main()` 将其计入独立的
    `timeout=` 计数，**不计入 mismatch、也不算通过**——参考语言个别病态基准本地跑不完属预期，
    CI 同样会因超时跳过，不应因此判整行 FAIL。
  - python 分支 `build()` 原先返回临时可执行路径（不存在）导致全部 RUN_ERR，改为返回源
    文件路径（python 直接跑源）。

## 验证

- `python3 tools/benchgen/verify_lang.py python` 不再因 `b15_loopsum` 等病态项全体 RUN_ERR；
  超时项归到 `timeout=`（参考语言预期行为）。
- `check_docs.py` PASS。

## 版本节奏

v4.74（工具链）→ python(v4.75) → csharp(v4.76) → d(v4.77)。
