# v4.72 — Java 基准源码扩到全 76 项（76/76 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Java / javac）

## 改动

- `bench/speed/java/`：补齐扩展集 `b31`–`b87`，覆盖全部 76 个规范基准，
  每个文件为 `class Main`（runner 以 `java -cp <dir> Main` 运行）。
- 修正 `b60_murmur.java`：移位掩码原本为 `0x1FFFFFFFFFFFFL`（56 位）且漏掉
  字面量 `L` 后缀导致被当成 32 位 int 字面量编译失败；对齐 C 的
  `0x1FFFFFFFFFFFLL`（52 位、带 `L` 后缀），正确隔离 `key >> 51` 的低 13 位，
  校验和恢复为 `1862168077173513743`。

## 验证

- `python3 tools/benchgen/verify_lang.py java` → `match=76 absent=0 mismatch=0`。
- 注：本机 `dotnet` 缺失，C# 无法本地校验；C# 仅在 CI windows 矩阵真跑，
  `run.py` 在无 SDK 时自动跳过并记入 notes。

## 版本节奏

java(v4.72) → 修 zig → python/csharp 视校验结果提交。
