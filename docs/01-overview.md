# 项目总览

## 1. 这是什么

Quelmara 是一门**从零实现的系统级编程语言**，包含语言规范、编译器、标准库与工具链。
编译器不依赖 LLVM/GCC/CRT：x86-64 指令编码、ELF64 与 PE32+ 文件写出、AArch64 发射器全部手写，
产物是**单文件可执行程序**，Windows 上只导入 `kernel32` / `ws2_32`。

设计取舍（按优先级）：

| 取舍 | 选择 | 代价 |
|---|---|---|
| 后端 | 只允许自研后端进产品链路；C99 后端仅作交叉验证 | 无成熟优化器可借力，性能靠手写 pass |
| 并发 | 多核默认开启（`parfor` / `spawn` / `chan`） | 运行时自带线程管理，栈固定 512 KB |
| 网络 | 原生 `tcp_*` / `udp_*` 内建 + IOCP reactor | 目前仅 Windows 有 reactor，Linux 侧待补 |
| 依赖 | 零第三方运行时，标准库纯 Quelmara 实现 | 库的成熟度要自己长 |
| 表达力 | 有意收窄：泛型单参数显式实例化、`match` 必须穷尽、无闭包 | 写通用代码时略啰嗦 |

## 2. 30 秒上手

Windows（仓库自带入口脚本 `quelmara.cmd`）：

```bat
quelmara build examples\hello.qma --target win -o build\hello.exe
build\hello.exe
```

等价于直接调 Python 引导层：

```bash
python tools/stage0/qlm_cli.py run examples/hello.qma --target win
python tools/stage0/qlm_cli.py test            # 跑内建 test 块
python tools/stage0/qlm_cli.py version         # 版本与能力
```

四个后端目标：

| `--target` | 产物 | 说明 |
|---|---|---|
| `native` | x86-64 ELF64 | Linux 默认，裸 syscall |
| `win` | x86-64 PE32+ | Windows 默认，无 CRT |
| `arm64` | AArch64 ELF64 | 部分特性未接，遇不支持形态编译期报错 |
| `c` | C99 源码 | **仅交叉验证**，不是产品链路 |

## 3. 最小程序

```quelmara
module hello

import std.core

fn greet(name: str) -> str {
    return "Hello, " + name
}

fn main() {
    print(greet("Quelmara"))
    print("cores online: " + cores().to_str())

    let mut i = 0
    while i < 3 {
        print("tick " + i.to_str())
        i = i + 1
    }
}
```

语言全貌见 [`02-language.md`](02-language.md)，标准库见 [`03-stdlib.md`](03-stdlib.md)。

## 4. 仓库结构

```
./                       # 仓库根
├── Quelmara.toml          # 全局配置：核数/网络/内存/构建（见 05-toolchain.md）
├── quelmara.cmd           # Windows 命令入口
├── docs/                  # 全部文档（本目录）
├── examples/              # 可直接运行的示例
├── bench/                 # 基准 + baseline.json + loadgen.py
├── tests/                 # .qma 回归 + 负向夹具 + 对拍/回归脚本
├── std/                   # 标准库模块（.qma 源码，编译期合并）
│   └── net/               # core.qma（槽位层）/ udp.qma
├── bootstrap/             # 自举层：lexer/ + parser/（Quelmara 写的）
├── tools/
│   ├── stage0/            # Python 引导层（当前唯一完整编译器）
│   ├── dev/               # 门禁、自举进度、推送、迁移脚本
│   └── qpm.py             # 包管理器
├── fixtures/              # 端到端夹具（srcproj / qpm-demo）
└── archive/               # 旧版本快照
```

### 关键文件

| 文件 | 作用 |
|---|---|
| `tools/stage0/qlm.py` | 词法/语法/类型推断/常量求值/模块加载/C99 后端 |
| `tools/stage0/qlm_native.py` | x86-64 编码器 + ELF64 写出 + 运行时 |
| `tools/stage0/qlm_opt.py` | 优化 pass |
| `tools/stage0/qlm_pe.py` | PE32+ 写出 + 导入表 |
| `tools/stage0/qlm_arm64.py` | AArch64 发射器 |
| `tools/stage0/qlm_cli.py` | 命令行驱动 |
| `bootstrap/lexer/qlm_lex.qma` | 自举词法器（已对拍通过） |
| `bootstrap/parser/qlm_parse.qma` | 自举声明级 parser（已对拍通过） |

各模块的**行数、职责边界、要改它当什么**见 [`04-compiler.md`](04-compiler.md) §2；
夹具/示例/基准/模块的**数量**见 [`05-toolchain.md`](05-toolchain.md) §5.1。
本文不复制这两类数字——复制的那一刻就开始漂移。

编译器内部结构见 [`04-compiler.md`](04-compiler.md)。

## 5. 当前状态一句话

后端（编码器/文件格式/reactor）成熟度最高，语言层居中，标准库与生态最薄。
具体数字与跑分**只在 [`06-status.md`](06-status.md) 维护**；缺什么、先做什么见
[`07-gaps.md`](07-gaps.md)。
