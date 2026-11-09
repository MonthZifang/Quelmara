# v4.90 · `b79_binary_tree` — -5.4%

- 所属版本：[v4.90](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b79_binary_tree.qma`
- C 参考源码：`bench/speed/c/b79_binary_tree.c`

## 根因

BST 插入循环 `v`/`node` 与 `root` 句柄

## 数据

| 项 | 值 |
|---|---|
| 改前 | 4948.89 ms |
| 改后 | 4679.24 ms |
| 变化 | **-5.4%** |
| 对 C 比值（改前 → 改后） | 2.37× → **2.24×** |
| C 参考耗时 | 2085.74 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`rbx`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b79_binary_tree.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b79_binary_tree.c -I bench/speed/c && /tmp/c
```
