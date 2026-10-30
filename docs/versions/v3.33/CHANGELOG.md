# v3.33 — 把 `read_source` 抽成零依赖模块，让所有读源码的工具都用上

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.32 遗留的"其它入口仍是裸 `open(...)`"
- 影响面：**工具链**（新增 `tools/stage0/qlm_src.py`，7 处读源码的点收口），
  `encoding_diag_test.py` 从 6 项扩到 9 项
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点

v3.32 修了编译主路径的编码诊断，CHANGELOG 末尾写着：

> 其它入口仍是裸 `open(..., encoding="utf-8")`：`tokfmt` / `qlm_doc` /
> `qlm_dbg` / `qlm_dbinfo` / `qlm_lsp` 等辅助工具。

这一版收掉它。但**直接改是行不通的** —— 先看清约束。

## 约束：不是所有模块都该 import `qlm`

`read_source` 原本写在 `qlm.py` 里。而读源码的模块有 7 个，它们大多
**不该** import 编译器：

`qlm_cli.py` 里有一段明确注释：

```python
import qlm_cache  # —— 缓存模块不依赖编译器：命中路径不许导入 qlm

# 源码扩展名，与 `qlm.SRC_EXT` 同值。**刻意不 import qlm 去取**：
# `import qlm` 在本机要 1.3 s，而缓存命中的整条路径只该花几十毫秒。
SRC_EXT = ".qma"
```

`import qlm` 要 1.3 秒。让 CLI 为了一个读文件函数去拉进整个编译器，
直接毁掉缓存命中的意义。

## 改法：抽成零依赖的 `qlm_src.py`

新模块只用 `os`，谁都能 import：

```python
from qlm_src import read_source
text = read_source(path)      # 失败抛 SyntaxError（带 文件:行:列）
```

提供两个函数：

| 函数 | 行为 |
|---|---|
| `read_source(path)` | 失败抛 `SyntaxError`（带文件名与 `行:列`） |
| `read_source_or_none(path)` | 任何失败返回 `None` |

第二个是给"读不到也不该崩"的场景用的 —— 调试器按路径找源码来显示，
找不到就退化成 `<source unavailable>`，不该让整个调试会话失败。

`qlm.py` 里保留 `from qlm_src import read_source` 作为转发别名，
`qlm.read_source` 与所有老调用点都不受影响（已验证
`qlm.read_source is qlm_src.read_source`）。

## 收口的 7 处

| 文件 | 用途 | 用哪个 |
|---|---|---|
| `qlm.py` | 编译主路径（v3.32 已改） | 转发别名 |
| `qlm_cli.py` | `lex` 子命令 + 扫 `test "` 块 | `read_source` |
| `qlm_doc.py` | 文档生成 / `fn_counts` | `read_source` |
| `qlm_fmt.py` | 格式化 | `read_source` |
| `qlm_fuzz.py` | 模糊测试读种子 | `read_source` |
| `qlm_dbinfo.py` | 统计主文件函数名 | `read_source` |
| `qlm_dbg.py` | 调试器显示源码 | **`read_source_or_none`** |

`qlm_dbg.py` 那处还顺带修了一个小缺陷：原来是

```python
try:
    with open(cand, encoding="utf-8") as f:
        ...
    break
except OSError:      # ← 只捕 OSError
    continue
```

编码错误抛的是 `UnicodeDecodeError`，**穿出了这个 except**，让调试会话
直接挂掉。现在用 `read_source_or_none` 一并归进"读不到"。

## 没有改的点

剩下 5 处 `open(..., encoding="utf-8")` 都是**非源码**：

| 文件:行 | 读的是什么 |
|---|---|
| `qlm_cache.py:451` | 缓存统计 JSON |
| `qlm_cli.py:779` | 缓存元数据 JSON |
| `qlm_dbg.py:1252` | 调试脚本（用户写的命令文件，不是源码） |
| `qlm_doc.py:278` | 已生成的文档（`--check` 比对用） |

这些不是源码，编码问题与编译器无关，而且失败语义不同（缓存坏了要
静默重建，不是报语法错）。**不动是对的**，不是漏了。

## 效果

三个工具对非 UTF-8 源文件的反应：

| 工具 | 改前 | 改后 |
|---|---|---|
| `doc` | 裸 `UnicodeDecodeError` | `[qlm] 编译错误：gbk.qma:3:4: 源文件不是合法的 UTF-8...` |
| `fmt --check` | 同上 | 同上 |
| `lex` | 同上 | 同上 |

三者都是退出码 1、一行诊断、**无 traceback**。

## 夹具

`encoding_diag_test.py` 从 6 项扩到 9 项，新增：

- `doc` 对非 UTF-8 给统一诊断、无 traceback；
- `fmt --check` 同上；
- `lex` 同上。

## 回归

全量 Windows 回归 PASS=350 FAIL=0 SKIP=0（与 v3.32 相同 —— 主回归里
case_encoding_diag 仍算**一条**用例，是脚本内部的断言从 6 项增到 9 项）。

## 遗留

`qlm_lsp.py` 也读源码（语言服务器），但它的读取走的是 `qlm_index`
的容错索引路径 —— 那条路径**故意**要能读"解析不了的文件"，
包括编码有问题的。给它是另一个判断（容错 vs 报错），不是简单替换。
留待后续单独处理。
