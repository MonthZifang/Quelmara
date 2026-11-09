# v4.89 · `b72_sort_insert` — -9.2%

- 所属版本：[v4.89](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b72_sort_insert.qma`
- C 参考源码：`bench/speed/c/b72_sort_insert.c`

## 根因

插入排序内层 `j`、`key` 两个热值，此前 `key` 溢出导致每轮两次往返

## 数据

| 项 | 值 |
|---|---|
| 改前 | 167.25 ms |
| 改后 | 151.83 ms |
| 变化 | **-9.2%** |
| 对 C 比值（改前 → 改后） | 2.79× → **2.54×** |
| C 参考耗时 | 59.85 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：未逐项核对（不写推测值）（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b72_sort_insert.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b72_sort_insert.c -I bench/speed/c && /tmp/c
```
