# v4.88 · `b59_mat_vec` — -23.5%

- 所属版本：[v4.88](CHANGELOG.md)
- 基准源码：`bench/speed/quelmara/b59_mat_vec.qma`
- C 参考源码：`bench/speed/c/b59_mat_vec.c`

## 根因

内层 `c`、`s` 与 `mat`/`vec_` 两个句柄竞争寄存器，此前只有部分入寄存器

## 数据

| 项 | 值 |
|---|---|
| 改前 | 4.28 ms |
| 改后 | 3.27 ms |
| 变化 | **-23.5%** |
| 对 C 比值（改前 → 改后） | 7.69× → **5.89×** |
| C 参考耗时 | 0.56 ms（`gcc -O2`，min of 5） |

**实测进寄存器的值**：`r14`（objdump 反汇编核实）

## 复核命令

```bash
cd /root/Quelmara/Quelmara
wine build/qlmc.exe build bench/speed/quelmara/b59_mat_vec.qma -o /tmp/x --target elf --no-bounds-check
chmod +x /tmp/x && /tmp/x          # 首行校验和须与 C 版一致，末行是纳秒
gcc -O2 -o /tmp/c bench/speed/c/b59_mat_vec.c -I bench/speed/c && /tmp/c
```
