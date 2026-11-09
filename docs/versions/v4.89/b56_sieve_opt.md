# v4.89 · `b56_sieve_opt` — -8.4%

- 所属版本：[v4.89](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b56_sieve_opt.qma`
- C 参考源码：`bench/speed/c/b56_sieve_opt.c`

## 根因

线性筛内层 `j`、`c` 与 `sieve` 句柄

## 数据

| 项 | 值 |
|---|---|
| 改前 | 83.15 ms |
| 改后 | 76.13 ms |
| 变化 | **-8.4%** |
| 对 C 比值（改前 → 改后） | 1.22× → **1.12×** |
| C 参考耗时 | 68.04 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r13`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b56_sieve_opt.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b56_sieve_opt.c -I bench/speed/c && /tmp/c
```
