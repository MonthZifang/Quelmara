# v4.90 · `b22_knapsack` — -34.4%

- 所属版本：[v4.90](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b22_knapsack.qma`
- C 参考源码：`bench/speed/c/b22_knapsack.c`

## 根因

内层递减计数器 `c` 与 `cand` 溢出；`wt.get(it)`/`vl.get(it)` 每轮重读

## 数据

| 项 | 值 |
|---|---|
| 改前 | 16.48 ms |
| 改后 | 10.81 ms |
| 变化 | **-34.4%** |
| 对 C 比值（改前 → 改后） | 13.47× → **8.83×** |
| C 参考耗时 | 1.22 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`rbx`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b22_knapsack.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b22_knapsack.c -I bench/speed/c && /tmp/c
```
