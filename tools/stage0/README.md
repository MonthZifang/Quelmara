# tools/stage0 —— stage-0 引导层（Python）

本目录是 Quelmara 编译器的 **stage-0 引导实现**，用 Python 写成。

## 它是什么

- **现在能用的唯一完整编译器**：`qlm.py`（词法/语法/推断 + C99 后端）、`qlm_native.py`（自研 x86_64 + PE）、`qlm_arm64.py`、`qlm_pe.py`、`qlm_opt.py` 等。
- **临时实现**：它的存在只为让语言能编译自己，最终必须被 `bootstrap/` 下的 Quelmara 实现逐块替换掉。

## 纪律（重要）

1. **禁止在此新增语言功能**。新能力必须先想清楚"stage-1 怎么实现"，Python 侧只作为引导与对拍参考。
2. **只允许两类改动**：修 bug（影响正确性）、配合 stage-1 的接口调整（如对拍输出格式）。
3. **每个模块都有退场目标**，见 `docs/SELFHOST.md` 的组件退场表；替换顺序是词法 → 语法 → 类型推断 → IR → 优化 → 编码器。
4. **测试工具不在自举约束内**：`tests/*.py`、`tests/*.sh`、`tools/dev/*` 可以一直用 Python/Node。

## 目录约定

```
tools/stage0/      # 引导层（Python，待退场）
bootstrap/         # 自举层（Quelmara，目标实现）
tests/             # 回归与对拍（Python/Node 永久可用）
tools/dev/         # 迁移、门禁、自举进度等开发脚本
```

## 运行

```bash
./quelmara build examples/hello.qma --target win -o build/hello.qex
python tools/stage0/qlm_cli.py version
```
