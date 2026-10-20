# 自举路线（Self-hosting）

> 原则：**编译器本体必须用 Quelmara 自己写**。Python 只是 stage-0 引导层，按组件逐个退场。
> 测试与开发工具不受此限制，可以长期使用 Python/Node。

## 1. 分层

| 层 | 目录 | 语言 | 地位 |
|---|---|---|---|
| stage-0 引导层 | `tools/stage0/` | Python | 临时，待退场 |
| stage-1 自举层 | `bootstrap/` | **Quelmara** | 目标实现 |
| 测试/工具 | `tests/`、`tools/dev/` | Python / Node | 永久允许 |

## 2. 组件退场表

| 组件 | stage-0 实现 | stage-1 目标 | 对拍口径 | 状态 |
|---|---|---|---|---|
| 词法 | `qlm.py::tokenize` | `bootstrap/lexer/qlm_lex.qma` | `KIND\|text\|line` 逐行 | ✅ 本轮 |
| 语法 | `qlm.py::Parser` | `bootstrap/parser/` | AST dump 规范化 | ⬜ 后续 |
| 类型推断 | `qlm.py` 推断层 | `bootstrap/typeck/` | 诊断文本 + IR 类型 | ⬜ 后续 |
| AST→IR | `qlm_native.py::Lower` | `bootstrap/ir/` | `.qir` 规范化 diff | ⬜ 后续 |
| 优化 | `qlm_opt.py` | `bootstrap/opt/` | `.qir` 规范化 diff | ⬜ 后续 |
| x86_64 编码 | `qlm_native.py::Codegen` | `bootstrap/codegen/x64/` | 反汇编逐指令 | ⬜ 后续 |
| ELF 写出 | `qlm_native.py` | `bootstrap/codegen/elf/` | 结构化字段比对 | ⬜ 后续 |
| PE 写出 | `qlm_pe.py` | `bootstrap/codegen/pe/` | 结构化字段比对 | ⬜ 后续 |
| AArch64 | `qlm_arm64.py` | `bootstrap/codegen/a64/` | 模拟器执行结果 | ⬜ 后续 |
| C99 后端 | `qlm.py::Codegen` | **不移植**（仅交叉验证） | — | — 永久保留 |

C99 后端是"交叉验证工具"，不是产品后端，因此不要求自举。

## 3. 进度

```bash
python tools/dev/selfhost_status.py
```

输出当前每个组件的实现归属、stage-1 是否就绪、对拍是否通过、自举代码行数占比。

## 4. 为什么词法器能先自举

词法器是本项目里**唯一不需要动态结构**的编译阶段：

| 需求 | 满足方式 |
|---|---|
| 读源码 | `read_text(path)`（C2） |
| 取文件名 | `args()`（C1） |
| 切出 token 文本 | `substr(s, lo, n)`（C3） |
| 逐字节扫描 | `s[i]` → 0..255（v0.12） |
| 关键字判断 | `s == "fn"` 链（str 内容相等已有） |
| 输出 | `print` + `to_str` |
| token 存储 | **不需要**：流式输出，单 token 前瞻用两个整数变量 |

不依赖可变长数组（vec）、不依赖 str 数组、不依赖位运算、不依赖 map 遍历 —— 这四项是 parser / IR / 编码器阶段才需要的。

## 5. 后续阶段的前置能力

| 阶段 | 还缺什么 |
|---|---|
| parser | `vec[T]`（可变长数组）、`[N]T` 装 struct/str、全局常量、`match` 支持 int |
| 类型推断 | map 遍历、stderr + 动态格式化、字典序比较 |
| IR / 优化 | 全局常量表、位运算（哈希/位打包） |
| 编码器 | 位运算 `& \| ^ ~ << >>`、真实整数宽度（u8/u32 回绕） |
| 真自举闭环 | 三轮固定点：stage0(源码) → S1，S1(源码) → S2，S1 与 S2 产物一致 |

## 6. 纪律

1. `tools/stage0/` **禁止新增语言功能**，只允许修 bug 与配合对拍的输出格式调整。
2. 任何组件从 stage-0 切到 stage-1 之前，必须先通过该组件的对拍门禁。
3. CLI 输出必须标明实现来源（`[qlm:stage0]` / `[qlm:stage1]`），避免"以为在测自举其实在跑 Python"。
