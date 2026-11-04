# v4.02 — quelmara 列在 Linux 上能出数了（qlmc ELF 后端接入 runner）

- 日期：2026-11-03
- 任务：CI 去掉 `quelmara0` 列之后，posix 上的 `quelmara` 列必须靠自己。
- 影响面：`bench/speed/run.py`、`.github/workflows/bench.yml`

## 问题

v3.94 给 qlmc 加了 ELF 后端，但 `run.py` 里的 `quelmara` 分支一直
**硬编码 PE**：

```python
exe = os.path.join(OUT, "qlm_" + b + EXE)      # .exe
r = subprocess.run([q, "build", src, "-o", exe], ...)   # 不带 --target
```

于是 Linux 上那列永远是空的 —— 只能靠 `quelmara0`（stage-0 的 ELF 后端）
凑数。而 stage-0 是 Python 写的参考实现，拿它代表"Quelmara 的性能"
并不诚实。

## 改动

1. **`run.py` 按平台选后端**：非 Windows 用 `--target elf`，产物是原生
   ELF，`chmod 755` 后直接 `exec`，计时口径与 C/Go 完全一致。
2. **qlmc 自身是 PE 产物**，Linux 上要用 `wine` 跑它 —— 加了 wine 包装。
   **不能用 `./qlmc.exe` 裸执行**：binfmt 的 `MZ` handler 会把 `argv[0]`
   重复塞进去（v3.63 实测，与 `tests/qlmc_test.py` 同因）。
   **只有编译器本身经过 wine**，它编出来的可执行文件是原生 ELF。
3. **`bench.yml` 的 Linux job 加「自举 qlmc」步骤**：`apt` 装 `wine64`，
   再用 stage-0 编出 `build/qlmc.exe`。

## 验证（本机 Linux + wine）

```
b10_ackermann  quelmara 0.0ms   vs C 0.1ms    4× 快
b12_gcd        quelmara 11413ms vs C 10509ms  1.09× 慢
校验和一致。
```

这是第一次让 `quelmara` 列在 Linux 上与 C 出现在同一张表里。
