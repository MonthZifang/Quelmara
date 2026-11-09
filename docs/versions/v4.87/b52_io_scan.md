# v4.87 · `b52_io_scan` — -32.5%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b52_io_scan.qma`
- C 参考源码：`bench/speed/c/b52_io_scan.c`

## 根因

单层求和，`sum`/`j` 与 `buf` 句柄本应全在寄存器，此前只有一个进了

## 数据

| 项 | 值 |
|---|---|
| 改前 | 7.47 ms |
| 改后 | 5.05 ms |
| 变化 | **-32.5%** |
| 对 C 比值（改前 → 改后） | 4.78× → **3.23×** |
| C 参考耗时 | 1.56 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b52_io_scan.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b52_io_scan.c -I bench/speed/c && /tmp/c
```
