# 原创性声明与实现差异（ORIGINALITY）

> 目的：说明本项目的代码来源与设计取舍，并给出可执行的自查手段。
> 结论先行：**编译器代码全部为本项目原创，不含从 Python / Go / Rust / C 项目复制的代码**；
> 运行时依赖只有语言标准库（Python 的 `tomllib`/`struct`/`subprocess` 等）。

## 1. 代码来源

| 部分 | 来源 | 说明 |
|---|---|---|
| 词法/语法/类型推断 | 原创 | 递归下降，手写优先级链，无 parser 生成器 |
| QuIR（中间表示） | 原创 | 函数 = vreg + 指令流，**非 SSA**；不是 LLVM IR / CPython bytecode / Go SSA 的任何变体 |
| 优化 pass | 原创 | 常量折叠、强度削减、魔数除法、范围传播、LICM、CSE-GVN、循环展开、DCE |
| x86_64 / AArch64 编码器 | 原创 | 手写 ModRM/REX/SIB 与 A64 位域编码，不调用汇编器 |
| ELF64 / PE32+ 写出 | 原创 | 手写文件头、程序头/节表、导入表、DIR64 重定位 |
| 运行时 | 原创 | 用 QuIR 自身实现（print/itoa/字符串/通道/哈希表），不链接 libc |
| C99 后端 | 原创 | 仅用于交叉验证，不是产品链路 |

**没有**使用任何第三方编译器框架、代码生成库、语法分析生成器或运行时库。

## 2. 依赖清单（全部为标准库）

`argparse` `os` `struct` `subprocess` `sys` `tomllib` `platform` `time` `json`
`glob` `shutil` `statistics` `hashlib` `tempfile` `re`

**可选开发依赖**（`try/except ImportError` 包住，缺失时自动跳过，不参与编译与测试）：
`capstone` —— 只用于 `qlm_arm64.py --disasm` 的反汇编级人工校验。

没有 requirements.txt / pyproject 依赖，没有 vendored 目录。

## 3. 与既有语言/实现的差异（为什么不是抄的）

| 维度 | Quelmara | Python | Go |
|---|---|---|---|
| 内存 | **arena + bump 分配器**，无 GC、无引用计数 | 引用计数 + 分代 GC | 三色并发 GC |
| 释放 | 帧级 arena 回卷（`arena { }` 块） | 自动 | 自动 |
| 中间表示 | **QuIR：非 SSA，vreg + 指令流** | CPython 字节码 | SSA |
| 产物 | 自研编码器直接产出裸 ELF/PE，**无 CRT、无 libc** | 解释执行 / .pyc | 自带链接器 + 运行时 |
| 整数 | 统一 64 位字，无任意精度 | 任意精度 int | 多宽度类型 |
| 字符串 | **零结尾字节串**，无长度前缀（`len` 是 O(n)） | PyUnicode 对象 | `{ptr,len}` |
| 切片 | `a[lo..hi]` 左闭右开；**str 切片是拷贝，切片/数组切片是零拷贝视图** | 切片拷贝 | `a[lo:hi]` 视图 |
| 移位 | `>>` 算术右移，`>>>` 逻辑右移（**两种都显式**） | 只有算术 `>>` | 只有逻辑 `>>`（无符号） |
| 优先级 | `\| < ^ < & < 比较 < << >> < 加减`（自定层次） | `\| < ^ < & < 移位 < 加减` | `\| ^` 在加法层、`<< >>` 在乘法层 |
| 并发 | `spawn`/`chan`/`parfor`，`[core] multicore=false` 时**编译期退化为同步调用** | GIL 线程 | goroutine 调度器 |
| 错误 | `result[T,E]` 枚举 + `?` 传播 + fail-fast（越界直接 exit 1） | 异常 | error 返回值 |
| 绑定 | `let` / `let mut`，标量**值语义拷贝**（不是别名） | 名字绑定对象 | 值/引用语义混合 |
| 模块 | 单文件模块，`import` 目前只做语法保留 | 包/模块 | package |

语法层面的自有点（都在 SPEC 里有定义，不是任何语言的子集照搬）：

- `a[lo..hi]` 对 `str` 是**拷贝语义**（因为 `str` 不可变），对切片/数组是**零拷贝视图**；
- `>>>` 与 `>>` 并列，避免"有符号右移到底怎么算"的隐式约定；
- `option[T]` / `result[T,E]` 由前端**合成枚举**（`__opt_T` / `__res_T_E`），不是语言内建的特例类型；
- `arena { }` 是**词法作用域**级别的内存回收，语义上不同于任何 GC 语言的作用域。

## 4. 自查

```bash
python tools/dev/check_origin.py
```

检查项：

1. 所有 `.py` 文件的 import 根模块必须属于标准库；
2. 代码中不得出现其它语言运行时的特征标识（`PyObject`/`Py_INCREF`/`goroutine`/
   `GOMAXPROCS`/`runtime.mallocgc`/`use std::`/`package main` 等）；
3. 仓库内不得存在 `vendor/`、`third_party/`、`*.whl`、`*.egg-info` 等第三方产物；
4. 统计自有代码规模，输出到报告里。

## 5. 许可证

本项目目前**未附加任何第三方许可证文本**，也不包含他人代码，因此不继承任何开源许可证义务。
对外发布前请作者自行选择许可证（MIT / Apache-2.0 / 双许可均可），
选定后再补 `LICENSE` 文件并在 `README.md` 标注。
