# v4.87 · `b1_int` — -6.3%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b1_int.qma`
- C 参考源码：`bench/speed/c/b1_int.c`

## 根因

单层 `(i*7)%13` 累加，`i`/`acc` 两个热值本应都在寄存器，此前 `acc` 溢出

## 数据

| 项 | 值 |
|---|---|
| 改前 | 66.95 ms |
| 改后 | 62.73 ms |
| 变化 | **-6.3%** |
| 对 C 比值（改前 → 改后） | 0.78× → **0.73×** |
| C 参考耗时 | 86.11 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`、`r13`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b1_int.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b1_int.c -I bench/speed/c && /tmp/c
```
