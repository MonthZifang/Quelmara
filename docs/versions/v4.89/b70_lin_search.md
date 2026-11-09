# v4.89 · `b70_lin_search` — -61.3%

- 所属版本：[v4.89](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b70_lin_search.qma`
- C 参考源码：`bench/speed/c/b70_lin_search.c`

## 根因

双层循环，内层 `k`、`found`、`target` 与 `a` 句柄同时活跃——全溢出时内层每轮 4 次内存往返

## 数据

| 项 | 值 |
|---|---|
| 改前 | 6590.95 ms |
| 改后 | 2552.97 ms |
| 变化 | **-61.3%** |
| 对 C 比值（改前 → 改后） | 3.23× → **1.25×** |
| C 参考耗时 | 2037.98 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r13`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b70_lin_search.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b70_lin_search.c -I bench/speed/c && /tmp/c
```
