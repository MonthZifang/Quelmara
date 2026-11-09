# v4.89 · `b39_hash_open` — -8.9%

- 所属版本：[v4.89](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b39_hash_open.qma`
- C 参考源码：`bench/speed/c/b39_hash_open.c`

## 根因

开放寻址探测循环 `i`、`h`、`step` 三个热值

## 数据

| 项 | 值 |
|---|---|
| 改前 | 109.32 ms |
| 改后 | 99.55 ms |
| 变化 | **-8.9%** |
| 对 C 比值（改前 → 改后） | 1.61× → **1.47×** |
| C 参考耗时 | 67.80 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`rbx`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b39_hash_open.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b39_hash_open.c -I bench/speed/c && /tmp/c
```
