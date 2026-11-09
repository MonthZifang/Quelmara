# v4.87 · `b76_io_line` — -7.9%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b76_io_line.qma`
- C 参考源码：`bench/speed/c/b76_io_line.c`

## 根因

单层扫描 `j`/`sum`/`line` 与 `lines` 句柄

## 数据

| 项 | 值 |
|---|---|
| 改前 | 14.34 ms |
| 改后 | 13.20 ms |
| 变化 | **-7.9%** |
| 对 C 比值（改前 → 改后） | 2.44× → **2.25×** |
| C 参考耗时 | 5.88 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`、`r14`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b76_io_line.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b76_io_line.c -I bench/speed/c && /tmp/c
```
