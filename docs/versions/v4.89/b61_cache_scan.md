# v4.89 · `b61_cache_scan` — -46.1%

- 所属版本：[v4.89](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b61_cache_scan.qma`
- C 参考源码：`bench/speed/c/b61_cache_scan.c`

## 根因

内层 `k`（静态 6 次使用）与累加器 `acc` 被判为"不值钱"，换给了循环外只用 1–2 次的变量

## 数据

| 项 | 值 |
|---|---|
| 改前 | 74.69 ms |
| 改后 | 40.28 ms |
| 变化 | **-46.1%** |
| 对 C 比值（改前 → 改后） | 6.18× → **3.33×** |
| C 参考耗时 | 12.09 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r13`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b61_cache_scan.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b61_cache_scan.c -I bench/speed/c && /tmp/c
```
