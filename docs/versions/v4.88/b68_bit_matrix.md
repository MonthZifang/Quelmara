# v4.88 · `b68_bit_matrix` — -11.1%

- 所属版本：[v4.88](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b68_bit_matrix.qma`
- C 参考源码：`bench/speed/c/b68_bit_matrix.c`

## 根因

位矩阵内层 `j` 与累加值两个热值，此前 `j` 溢出

## 数据

| 项 | 值 |
|---|---|
| 改前 | 2.51 ms |
| 改后 | 2.23 ms |
| 变化 | **-11.1%** |
| 对 C 比值（改前 → 改后） | 1.90× → **1.69×** |
| C 参考耗时 | 1.32 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b68_bit_matrix.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b68_bit_matrix.c -I bench/speed/c && /tmp/c
```
