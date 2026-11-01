# v3.72 — `dumpasm.py --diff`：不依赖 capstone 的产物差异对比

- 日期：2026-11-01
- 任务：v3.71 排查 §7.18 时，反复手写"PE 解析 + 逐字节对比 + 按段分组"
  的临时代码（写了 4 次）。本版把它固化成工具。
- 影响面：`tools/dev/dumpasm.py`（新增 `--diff` 模式）
- 代码改动：约 60 行

## 用法

```bash
python tools/dev/dumpasm.py --diff a.exe b.exe        # 列出所有差异段
python tools/dev/dumpasm.py --diff a.exe b.exe -n 8   # 只看前 8 处
```

输出形如：

```
A: a.exe  .text VA=0x1000 size=0x9ee00
B: b.exe  .text VA=0x1000 size=0x9ee00
差异段：23921 处（区间取 min(size)，共 0x9ee00 字节）

  [2] VA 0x114c5..0x114c5（1 字节）
      A: 8d d0 fd ff ff 49 c1 e1 03 4c 89 c9 e8 93 fc fe ff
      B: 8d d0 fd ff ff 49 c1 e1 06 4c 89 c9 e8 93 fc fe ff

下一步：用 `qlmc build <src> --addrdump` 把 VA 映射回函数名
```

## 为什么有用

排查"同源码、不同编译器产物不同"时：

* `cmp` 只给**第一个**差异点，且不给上下文；
* 反汇编工具（`dumpasm.py` 原有模式）需要 `capstone`，而**很多环境装不上**
  （本机 `pip` 都没有）。

`--diff` 只做裸字节对比 + **按连续差异段分组**，不需要任何外部依赖。

v3.71 实测：`S2_FULL` vs `S2_BY_V65` 的 6778 处差异里，绝大多数是
"代码整体偏移后全部错位"的假差异；真正有意义的只有前 2 处
（`shl r9,3` vs `shl r9,6` / `imul 0x38`）。**先看前几处就够定位了。**

## 顺带修：capstone 导入改成惰性

原来 capstone 在**模块顶层**导入，导致没有 capstone 时**连 `--diff` 都跑不了**
（`sys.exit(2)` 在导入期就触发了）。改成只在反汇编分支里导入：

```python
def _capstone():
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64
        return Cs, CS_ARCH_X86, CS_MODE_64
    except ImportError:
        print("需要 capstone（可选开发依赖）：pip install capstone")
        sys.exit(2)
```

## 验证

| 命令 | 结果 |
|---|---|
| `--diff` 两个真实产物（v3.71 修复前后） | ✅ 正确列出差异段，`[2]`/`[3]` 正是那两处 stride 差异 |
| `--diff` 同一文件 | ✅ `差异段：0 处` |
| 反汇编模式（无 capstone） | ✅ 友好报错，不是 traceback |
| `--diff` 缺参数 | ✅ 打印用法 |
