# v4.01 — CI 装齐对比语言 + Rust 14 项基准

- 日期：2026-11-03
- 任务：把"11 种对比语言"从"登记了但没源码"推进到"能跑"。
- 影响面：`.github/workflows/bench.yml`、`bench/speed/rust/`（14 项 + README）

## CI 装工具链

`bench.yml` 的 Linux job 新增「额外对比语言」步骤：rustup / zig / choosenim /
gfortran。**每一步都 `|| true`** —— 某一种装不上不该让整条基准确链失败，
`run.py` 会明确跳过并把原因写进结果。

`--langs` 从 `quelmara0 c go python` 扩到
`quelmara0 c cpp go rust zig nim fortran python`。

## Rust 14 项

`b10_ackermann` … `b28_matrix` 全部手写，与 C / quelmara 版算法逐字等价。

**一个必须显式处理的语义差异**：溢出。C 用 `uint64_t` 回绕、quelmara 用
int64 回绕，而 Rust 的普通 `*` / `+` 在 debug 构建会 **panic**、release
构建是**未定义行为**。所以 Rust 版一律用 `wrapping_mul` / `wrapping_add`
—— 这是唯一能和三语言对上口径的写法。

## 这批源码**没有在本地验证过**

开发机没有 `rustc`。语法正确性完全靠 CI 验证。`bench/speed/rust/README.md`
里写清了这一点和写法规约，免得下一个人误以为验证过。

**如果 CI 报某个文件语法错，改那一个就行** —— 14 个文件之间没有共享代码。

## 尚未完成

* Rust 还缺 `b1`…`b9` 那 10 项（原有基准）；
* Zig / Nim / Fortran / D / Ada 源码一个都还没写；
* C# 仍未接（.NET 需要 csproj，`dotnet run` 启动开销会污染纳秒计时）。

这几块是下一步。
