# v4.87 · `b66_integrate` — -9.8%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b66_integrate.qma`
- C 参考源码：`bench/speed/c/b66_integrate.c`

## 根因

`f(i)` 内联后 `acc`/`i` 与外层 `x` 竞争寄存器，此前 `acc` 被溢出

## 数据

| 项 | 值 |
|---|---|
| 改前 | 41.79 ms |
| 改后 | 37.69 ms |
| 变化 | **-9.8%** |
| 对 C 比值（改前 → 改后） | 2.95× → **2.66×** |
| C 参考耗时 | 14.17 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r14`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b66_integrate.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b66_integrate.c -I bench/speed/c && /tmp/c
```
