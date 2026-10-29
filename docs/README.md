# Quelmara 文档索引

这是**唯一文档入口**。仓库根目录只有一份导航桩 `README.md`，其余文档全部在本目录下。

> 本目录的存放规则见 [`00-convention.md`](00-convention.md)。新增/修改文档前先读它。

## 按用途查找

| 我想…… | 读这份 |
|---|---|
| 知道这个项目是什么、怎么跑第一个程序 | [`01-overview.md`](01-overview.md) |
| 写代码，查语法、类型、内建函数 | [`02-language.md`](02-language.md) |
| 用标准库（HTTP/JSON/加密/容器/网络） | [`03-stdlib.md`](03-stdlib.md) |
| 看懂编译器内部、改优化器或后端 | [`04-compiler.md`](04-compiler.md) |
| 用 CLI、改配置、装依赖、跑测试 | [`05-toolchain.md`](05-toolchain.md) |
| 知道现在到哪了、跑分多少、支持哪些平台 | [`06-status.md`](06-status.md) |
| 知道什么还不能做、下一步做什么 | [`07-gaps.md`](07-gaps.md) |
| 看某个版本改了什么 | [`versions/`](versions/) |
| 看 2.x 线（99 次更新）的整体复盘 | [`versions/v3.00/REPORT.md`](versions/v3.00/REPORT.md) |

## 文档清单

| 文件 | 职责（只管这件事） | 不管什么 |
|---|---|---|
| `00-convention.md` | 文档目录结构、命名、版本文件夹规则、门禁 | 任何技术内容 |
| `01-overview.md` | 定位、快速开始、仓库结构、最小示例 | 语法细节、性能数字 |
| `02-language.md` | 词法/类型/语句/表达式/特性语义/内建函数 | 标准库 API、实现细节 |
| `03-stdlib.md` | `std/` 下每个模块的公开 API 与边界 | 语言语法、性能对比 |
| `04-compiler.md` | 编译流水线、QuIR、优化 pass、三后端、运行时 | CLI 用法、语言教程 |
| `05-toolchain.md` | CLI、配置、src 布局、qpm、测试与门禁、CI | 语言语义、编译器算法 |
| `06-status.md` | **所有实测数字的唯一出处**：回归/自举/性能/平台 | 能力缺口的论证 |
| `07-gaps.md` | 缺口清单与优先级路线 | 实测数字（引用 06） |
| `versions/vX.Y.Z/CHANGELOG.md` | 该版本的任务、改动、验证 | 当前状态口径 |

## 三条硬规则

1. **数字只写一处**：回归项数、自举行数、基准耗时只允许出现在 `06-status.md` 和 `versions/*/CHANGELOG.md`。其它文档一律写"见 `06-status.md`"。
2. **能力断言必须有证据**：写"支持"要附 `文件:行` 或一条能跑的命令；写不出证据的标 🚧。
3. **一次任务一个版本文件夹**：每次提交前新建 `versions/vX.Y.Z/CHANGELOG.md`，写清任务、改动文件、验证命令与结果。规则细节见 `00-convention.md`。
