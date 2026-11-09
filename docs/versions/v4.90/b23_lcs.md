# v4.90 · `b23_lcs` — -10.7%

- 所属版本：[v4.90](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b23_lcs.qma`
- C 参考源码：`bench/speed/c/b23_lcs.c`

## 根因

DP 滚动数组内层 `j`、`dp0`/`dp1` 三值跨轮存活

## 数据

| 项 | 值 |
|---|---|
| 改前 | 61.30 ms |
| 改后 | 54.75 ms |
| 变化 | **-10.7%** |
| 对 C 比值（改前 → 改后） | 5.93× → **5.29×** |
| C 参考耗时 | 10.34 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b23_lcs.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b23_lcs.c -I bench/speed/c && /tmp/c
```
