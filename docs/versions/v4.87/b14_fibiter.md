# v4.87 · `b14_fibiter` — -18.9%

- 所属版本：[v4.87](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b14_fibiter.qma`
- C 参考源码：`bench/speed/c/b14_fibiter.c`

## 根因

迭代 fib 是 `a`/`b`/`i` 三值互相依赖的加法链，必须同时活着——此前 `i` 被溢出

## 数据

| 项 | 值 |
|---|---|
| 改前 | 753.62 ms |
| 改后 | 611.12 ms |
| 变化 | **-18.9%** |
| 对 C 比值（改前 → 改后） | 1.72× → **1.40×** |
| C 参考耗时 | 437.96 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r12`、`r13`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b14_fibiter.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b14_fibiter.c -I bench/speed/c && /tmp/c
```
