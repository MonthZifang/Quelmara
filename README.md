# Quelmara

> **原生编译 · 多核默认 · 网络原生 · 自研后端**
> x86-64 ELF ｜ PE32+（无 CRT）｜ AArch64 ｜ C99（仅交叉验证）

一门**从零自研的系统级编程语言**——语言、编译器、标准库、工具链全栈自有，
不依赖 LLVM / GCC / CRT：指令编码、ELF64 与 PE32+ 写出、AArch64 发射器全部手写，
产物是单文件可执行程序。设计取舍与项目定位见 [`docs/01-overview.md`](docs/01-overview.md)。

**[`docs/README.md`](docs/README.md) 是唯一文档入口**；本页只做导航与快速上手。

---

## 三十秒上手

Windows（仓库自带入口脚本 `quelmara.cmd`）：

```bat
quelmara build examples\hello.qma --target win -o build\hello.exe
build\hello.exe
```

任何有 Python 的平台（引导层等价入口）：

```bash
python tools/stage0/qlm_cli.py run examples/hello.qma --target win
python tools/stage0/qlm_cli.py version     # 版本与能力清单
```

四个后端目标、最小程序与仓库结构见 [`docs/01-overview.md`](docs/01-overview.md)。

---

## 按用途导览

| 我想…… | 读这份 |
|---|---|
| 跑第一个程序 | [`docs/01-overview.md`](docs/01-overview.md) |
| 写代码：语法 / 类型 / 内建函数 | [`docs/02-language.md`](docs/02-language.md) |
| 用标准库：HTTP / JSON / 加密 / 容器 / 网络 | [`docs/03-stdlib.md`](docs/03-stdlib.md) |
| 改编译器：流水线 / QuIR / 优化 pass / 三后端 | [`docs/04-compiler.md`](docs/04-compiler.md) |
| 用 CLI / 改配置 / 装依赖 / 跑测试与门禁 | [`docs/05-toolchain.md`](docs/05-toolchain.md) |
| 看实测状态与跑分（**全部数字的唯一出处**） | [`docs/06-status.md`](docs/06-status.md) |
| 看还缺什么、下一步做什么 | [`docs/07-gaps.md`](docs/07-gaps.md) |
| 看某个版本改了什么 | [`docs/versions/`](docs/versions/) |

## 现状速写

- **版本与能力清单**：`python tools/stage0/qlm_cli.py version`
- **缺口与路线**：语言层 / 标准库 / 工具链已逐项收口，剩余移植项与推进顺序见 [`docs/07-gaps.md`](docs/07-gaps.md)
- **回归与跑分**：以 [`docs/06-status.md`](docs/06-status.md) 为唯一口径，本页不复制数字

---

> 文档规则见 [`docs/00-convention.md`](docs/00-convention.md)：实测数字只出现在
> `06-status.md` 与各版本 `CHANGELOG.md`；能力断言须有文档证据；一次任务一个版本文件夹。
