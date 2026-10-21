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
| 词法 | `qlm.py::tokenize` | `bootstrap/lexer/qlm_lex.qma` | `KIND\|RAW\|LINE` 逐行 **92/92 全等** | ✅ v1.0 |
| 语法（声明级） | `qlm.py::Parser` | `bootstrap/parser/qlm_parse.qma` | `module/import/struct/enum/fn` 签名 **87/87 全等** | ✅ v1.3 |
| 语法（函数体） | `qlm.py::Parser` | 同上（Phase 1 核心子集已写，`--body` 模式） | S 表达式协议 `tests/bodydiff.py`：dump 一致 94 / 分叉 636 / SKIP 不同步 25（清单化推进） | 🟡 进行中 |
| 类型推断 | `qlm.py` 推断层 | `bootstrap/typeck/` | 负向夹具体检：两阶段都必须报错且类别一致 | ⬜ 后续 |
| AST→IR | `qlm_native.py::Lower` | `bootstrap/ir/` | QuIR 规范 diff（已可用） | 🟡 骨架就绪 |
| 优化 | `qlm_opt.py` | `bootstrap/opt/` | QuIR 优化前后 diff | ⬜ 后续 |
| x86_64 编码 | `qlm_native.py::Codegen` | `bootstrap/codegen/x64/` | 反汇编逐指令 + 确定性 | 🟡 骨架就绪 |
| ELF 写出 | `qlm_native.py` | `bootstrap/codegen/elf/` | 魔数/入口/确定性（已可用） | 🟡 骨架就绪 |
| PE 写出 | `qlm_pe.py` | `bootstrap/codegen/pe/` | MZ/PE32+/仅 kernel32/确定性 | 🟡 骨架就绪 |
| AArch64 | `qlm_arm64.py` | `bootstrap/codegen/a64/` | IR 架构无关性 **50/50 全等** + 模拟器执行 | 🟡 骨架就绪 |
| C99 后端 | `qlm.py::Codegen` | **不移植**（仅交叉验证） | — | — 永久保留 |

### 现已可用的对拍脚本

| 脚本 | 守的是什么 | 当前结果 |
|---|---|---|
| `tests/lexdiff.py` | 词法器逐 token 一致 | 92/92 |
| `tests/parsediff.py` | 声明级 AST 一致 | 87/87 |
| `tests/irdiff.py` | **QuIR 架构无关**：x86_64 与 aarch64 除 syscall 号外逐字节相同 | 50/50（19 skip：a64 无 chan/map/spawn） |
| `tests/emitdiff.py` | 发射层**确定性**（同输入两次构建字节相同）+ ELF/PE 结构与「无 CRT」 | 10/10 |

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

| 阶段 | 状态 |
|---|---|
| parser 需要的容器 | ✅ `vec[T]`（v1.2）；元素类型支持**标量 / struct / enum**（v1.3，`tests/t37_vecagg.qma` 按值语义验证），AST 节点表可直接 `vec[Node]` |
| parser 需要的符号表枚举 | ✅ `for k in map`（v1.2，顺序实现定义） |
| parser 需要的按值缓冲 | ✅ `[N]T` 作参数/返回值（v1.2，自研后端） |
| parser 需要的位运算 | ✅ `& \| ^ ~ << >> >>>`（v1.1）+ `0x` 字面量 |
| parser 需要的常量表 | ✅ 顶层 `const`（v1.1）+ 跨 import 可见（v1.5 两遍解析） |
| 类型推断 | ✅ map 遍历 / 字典序 / `eprint` 动态诊断 |
| 编码器 | ✅ 位运算齐全；仍缺真实整数宽度（`u8/u32` 只有类型名、无截断回绕，见 `docs/GAPS.md §2`） |
| **仍缺（容器形态）** | `vec[vec[T]]` / `map[str]Struct` 不支持（`map` 值仅标量），嵌套聚合按 1 槽占位；复杂 AST 仍需扁平化或索引编码 |
| 真自举闭环 | 三轮固定点：stage0(源码) → S1，S1(源码) → S2，S1 与 S2 产物一致 |

## 6. 纪律

1. `tools/stage0/` **禁止新增语言功能**，只允许修 bug 与配合对拍的输出格式调整。
2. 任何组件从 stage-0 切到 stage-1 之前，必须先通过该组件的对拍门禁。
3. CLI 输出必须标明实现来源（`[qlm:stage0]` / `[qlm:stage1]`），避免"以为在测自举其实在跑 Python"。
