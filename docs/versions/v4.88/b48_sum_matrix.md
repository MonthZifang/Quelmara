# v4.88 · `b48_sum_matrix` — -47.7%

- 所属版本：[v4.88](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b48_sum_matrix.qma`
- C 参考源码：`bench/speed/c/b48_sum_matrix.c`

## 根因

内层只有 `c`/`s` 两个热变量，却因外层 `r`/`total` 静态计数更高而被挤出寄存器

## 数据

| 项 | 值 |
|---|---|
| 改前 | 2.38 ms |
| 改后 | 1.24 ms |
| 变化 | **-47.7%** |
| 对 C 比值（改前 → 改后） | 5.14× → **2.69×** |
| C 参考耗时 | 0.46 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r14`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b48_sum_matrix.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b48_sum_matrix.c -I bench/speed/c && /tmp/c
```
