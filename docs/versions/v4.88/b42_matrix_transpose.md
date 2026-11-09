# v4.88 · `b42_matrix_transpose` — -15.3%

- 所属版本：[v4.88](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b42_matrix_transpose.qma`
- C 参考源码：`bench/speed/c/b42_matrix_transpose.c`

## 根因

内层 `r`/`c` 两个计数器本应都在寄存器，此前 `c` 被换出

## 数据

| 项 | 值 |
|---|---|
| 改前 | 9.62 ms |
| 改后 | 8.15 ms |
| 变化 | **-15.3%** |
| 对 C 比值（改前 → 改后） | 1.40× → **1.18×** |
| C 参考耗时 | 6.88 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b42_matrix_transpose.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b42_matrix_transpose.c -I bench/speed/c && /tmp/c
```
