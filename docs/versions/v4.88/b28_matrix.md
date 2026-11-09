# v4.88 · `b28_matrix` — -31.1%

- 所属版本：[v4.88](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b28_matrix.qma`
- C 参考源码：`bench/speed/c/b28_matrix.c`

## 根因

三重循环最内层 `j`/累加值与 `c` 句柄溢出；`r*n`/`k*n` 每轮重算（需 LICM，仍未做）

## 数据

| 项 | 值 |
|---|---|
| 改前 | 773.21 ms |
| 改后 | 532.60 ms |
| 变化 | **-31.1%** |
| 对 C 比值（改前 → 改后） | 12.84× → **8.84×** |
| C 参考耗时 | 60.22 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r13`、`r14`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b28_matrix.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b28_matrix.c -I bench/speed/c && /tmp/c
```
