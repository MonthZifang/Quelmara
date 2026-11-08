# v4.65 — 基准对比工具链与 11 语言接线

- 日期：2026-11-08
- 性质：基准基础设施（不改动编译器）

## 目标

把 bench/speed 从"4 语言核心"扩展到"11 种对比语言全接线"，并保证
每个语言都能用统一脚本校验"逐字节相同校验和"，从而让 diff 门禁在 CI 里
能自动发现任何一份写错的源码。

## 改动

- `bench/speed/run.py`：`EXTRA_LANGS` 接入 `java`（javac，本机可验证）与
  `csharp`（dotnet/csc，仅 CI windows 能真跑、本机无 SDK 时自动跳过）；
  `LANGS` 默认列表同步加入 `java` / `csharp`。
- 新增 `tools/benchgen/` 校验工具链：
  - `collect_c.py`：编译并运行全部 76 个 C 基准，导出权威校验和到
    `/tmp/c_checksums.json`（每行 `T` 之前的内容）。
  - `verify_lang.py`：对某个语言逐个编译+运行，与 C 校验和逐项比对，
    输出 `match / absent / mismatch`，是各语言源码能否入库的硬门禁。
  - `SPEC.md`：给生成源码的协作者看的规范（算法逐字等价、输出格式、
    浮点/字符串/递归坑位）。
- `.gitignore`：忽略 `bench/speed/**` 下编译产物（`*.o` `*.ali` `*.mod`
  `*.class` `*.bin/`），避免把构建残留入库。

## 验证

- `python3 tools/benchgen/verify_lang.py <lang>` 对 go/cpp/rust/python/ada/
  nim/d 等已就绪语言逐项校验（详见后续各语言版本）。
- `python3 tools/dev/check_docs.py` PASS。

## 版本节奏

v4.65 为接线 + 工具链。随后每个语言的源码覆盖独立成版本提交：
go / cpp / rust / python / ada / nim / d / fortran / zig / java / csharp，
每补一种语言即一次提交、推到 GitHub。
