# v4.45 — `Quelmara.toml` 的 `heap_limit_mb` 真正生效

- 日期：2026-11-05
- 任务：v4.44 只做了命令行 `--heap-mb`，配置文件那条路还是断的。
- 结论：**已接通**，优先级为 命令行 > Quelmara.toml > qlmc 编译期默认。

## 为什么不在 qlmc 里读 toml

qlmc 唯一的文件读取函数 `_read_text` 走的是 Win32 API
（`_CreateFileA` / `_ReadFile`），在 ELF/Linux 上不可用。要让 qlmc 自己能读
配置文件，得先给它加一套可移植的文件 IO —— 那是另一个工程。

所以改成**由调用方读配置、把值传进来**：

```
bench/speed/run.py  ──读 Quelmara.toml──>  --heap-mb 512  ──>  qlmc
```

`run.py` 本身是跨平台的（Windows 直接跑、Linux 用 wine 包 qlmc），
读 toml 的部分是十几行纯 Python，不需要引第三方库。

## 实现

`heap_mb_from_toml()`：逐行扫，跟踪 `[section]`，只在 `[memory]` 段里找
`heap_limit_mb = N`。注释用 `#` 截掉，空行跳过，值非正数当作"没配"。
解析失败一律返回 `None`（不因为配置文件写坏了就让基准挂掉）。

优先级在 `main()` 里定：

```python
HEAP_MB = args.heap_mb if args.heap_mb else heap_mb_from_toml()
```

并打印一行来源，避免"到底用了哪个值"说不清：

```
[heap] 堆上限 512 MB（Quelmara.toml）
[heap] 堆上限 128 MB（命令行 --heap-mb）
```

## 验证

```
# toml 里写 512 -> 读出来 512
# 改成 384 -> 读出来 384（动态生效，不是缓存）
run.py --only b1_int          -> [heap] 512 MB（Quelmara.toml）
run.py --only b1_int --heap-mb 128 -> [heap] 128 MB（命令行）
```

两者校验和一致、编译正常。

## 仍未做

* **代码内按作用域设限**（对单个 vec / 单个函数 / 单个文件设上限）：
  需要把分配器从"单一 bump 游标"改成 arena 分区，是架构级改动。
* vec 内联布局：v4.44 试过，校验和对、快 18%，但自举超时 → 回退。
* 寄存器分配改进、SIMD。
