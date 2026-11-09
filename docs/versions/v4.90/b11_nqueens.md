# v4.90 · `b11_nqueens` — -7.2%

- 所属版本：[v4.90](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b11_nqueens.qma`
- C 参考源码：`bench/speed/c/b11_nqueens.c`

## 根因

递归 `solve` 内的 `c`/`k`/`ok` 与 `col` 句柄；递归帧多，寄存器更紧张

## 数据

| 项 | 值 |
|---|---|
| 改前 | 2169.76 ms |
| 改后 | 2013.44 ms |
| 变化 | **-7.2%** |
| 对 C 比值（改前 → 改后） | 1.74× → **1.61×** |
| C 参考耗时 | 1248.77 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r14`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b11_nqueens.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b11_nqueens.c -I bench/speed/c && /tmp/c
```
