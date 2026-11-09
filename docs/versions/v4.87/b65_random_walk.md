# v4.87 · `b65_random_walk` — -17.0%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b65_random_walk.qma`
- C 参考源码：`bench/speed/c/b65_random_walk.c`

## 根因

LCG 状态 `seed`、累加器 `acc` 与 `i` 三个值跨轮存活，此前有一个每轮 store→load 两次

## 数据

| 项 | 值 |
|---|---|
| 改前 | 41.35 ms |
| 改后 | 34.31 ms |
| 变化 | **-17.0%** |
| 对 C 比值（改前 → 改后） | 4.10× → **3.40×** |
| C 参考耗时 | 10.10 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`、`r13`、`r14`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b65_random_walk.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b65_random_walk.c -I bench/speed/c && /tmp/c
```
