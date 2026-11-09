# v4.90 · `b49_floyd` — -43.2%

- 所属版本：[v4.90](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b49_floyd.qma`
- C 参考源码：`bench/speed/c/b49_floyd.c`

## 根因

三重循环最内层 `c`、`d1`、`d2` 与 `dist` 句柄全部溢出，每轮两次 store→load

## 数据

| 项 | 值 |
|---|---|
| 改前 | 23.61 ms |
| 改后 | 13.41 ms |
| 变化 | **-43.2%** |
| 对 C 比值（改前 → 改后） | 8.77× → **4.98×** |
| C 参考耗时 | 2.69 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`、`r14`、`r15`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b49_floyd.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b49_floyd.c -I bench/speed/c && /tmp/c
```
