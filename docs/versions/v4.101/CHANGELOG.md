# v4.101 — macOS Mach-O 后端（容器格式，第一块）

- 日期：2026-11-10
- 任务：目标④「尽可能同步开展 macOS 后端」的第一块
- 影响面：编译器（新增 Mach-O 写出器 / `--target macho`）

## 背景：四轮下来 macOS 是唯一零进展的目标

四个目标里，①（自举 8/8）、②（Linux/Windows 后端 + 多核）、③（统一核心 +
自动并行）都有实质推进，只有 ④ 完全没动 —— qlmc 只能出 PE32+ 和 ELF64。

本版把 Mach-O **容器格式**做出来：能产出结构合法的 x86-64 Mach-O 可执行
文件，并被 Apple 的工具链正确解析。

## 布局

```
偏移 0                    mach_header_64               (32 字节)
                          LC_SEGMENT_64 __PAGEZERO     (72 字节)
                          LC_SEGMENT_64 __TEXT         (72 字节)
                          LC_MAIN                      (24 字节)
hdr_end (=200)            代码
                          只读数据
```

三条设计选择：

1. **`__PAGEZERO` 必须是 [0, 4GB)**。这是 macOS 的防空指针保护 —— 任何
   `NULL` 解引用都会立刻崩，与 Linux 靠内核 mmap_min_addr 是两种做法。
2. **合并成单个 `__TEXT` 段**。qlmc 的 ELF 后端也是单 `PT_LOAD`；macOS 允许
   `__TEXT` 带 `VM_PROT_EXECUTE`，数据放同一个段里省掉 `__DATA` 的页对齐
   计算。做"代码与数据分离"是下一步的事。
3. **`fileoff`/`filesize` 与 `vmaddr`/`vmsize` 按页（0x1000）对齐**，这是
   dyld 的硬要求，不对齐会被内核直接拒绝。

## 踩到的坑：`vmaddr` 多加了 PAGEZERO

第一版写的是 `MACHO_BASE + MACHO_PAGEZERO_SIZE`：

```
__TEXT vmaddr 0x0000000200000000     ← 错
```

因为 `MACHO_BASE`（0x100000000）**本身**就是 `__TEXT` 的起始地址，
`__PAGEZERO` 占的是 [0, 4GB) 那段**不可访问**区间。再加一次就成了
0x200000000，dyld 会拒绝加载。

修完：

```
__TEXT vmaddr 0x0000000100000000     ← 标准 macOS 布局
```

## 验证

用 Apple 工具链的 Linux 移植版（本机有 LLVM 20）逐条核对：

```
$ file /tmp/h_m2
/tmp/h_m2: Mach-O 64-bit x86_64 executable

$ llvm-objdump --macho --all-headers /tmp/h_m2
Mach header
      magic cputype cpusubtype  caps    filetype ncmds sizeofcmds      flags
MH_MAGIC_64  X86_64        ALL  0x00     EXECUTE     3        168 0x00000000
Load command 0
      cmd LC_SEGMENT_64
  cmdsize 72
  segname __PAGEZERO
   vmaddr 0x0000000000000000
   vmsize 0x0000000100000000
Load command 1
      cmd LC_SEGMENT_64
  cmdsize 72
  segname __TEXT
   vmaddr 0x0000000100000000
   vmsize 0x0000000000002000
  fileoff 0
 filesize 5184
  maxprot rwx
 initprot r-x
Load command 2
       cmd LC_MAIN
   cmdsize 24
  entryoff 200
 stacksize 0
```

三条加载命令全部正确解析。

| 命令 | 结果 |
|---|---|
| `--target macho` 编 `examples/hello.qma` | 5184 字节，`file` 识别为 Mach-O x86_64 executable |
| `llvm-objdump --macho --all-headers` | 3 条加载命令全部正确 |
| 自举两代 | 逐字节不动点 |
| 76 个基准 checksum vs C（PE 路径） | **76/76 一致** |
| `python3 tools/dev/check_docs.py` | PASS |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 MACHO_* 常量、`build_macho`、`_write_segname`；`--target` 接受 `macho`/`macos`/`mac`；输出分派加 `tgt == 2` |

## 已知边界 / 遗留（**重要**）

- **这个产物在 macOS 上还跑不起来**。运行库仍是 Linux syscall 版
  （`write=1` / `exit=60`），而 macOS 的 syscall 号带 `0x2000000` 前缀
  （`write=0x2000004` / `exit=0x2000001`），且部分系统调用语义不同。
  要真正在 macOS 上执行，下一步得写一套 `_gen_*_macho` 运行库例程。
- 没有 `__DATA` 分段（代码与数据同段），没有节表（`nsects = 0`）。
- 没有符号表、没有 `LC_LOAD_DYLINKER`（纯静态，不需要 dyld 加载动态库）。
- 只支持 x86-64，**不支持 arm64**（Apple Silicon 需要 `MH_MAGIC_64` +
  `CPU_TYPE_ARM64` + `LC_UNIXTHREAD` 设初始 PC，与 `LC_MAIN` 的做法不同）。
- 本机是 Linux/x86-64，**无法执行** Mach-O 产物 —— 只能做结构验证。
