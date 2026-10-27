# v2.76 — 堆从 .bss 换成 VirtualAlloc 私有页；比较不再搬寄存器（b4 −54%）

- 日期：2026-10-27
- 任务：性能 —— b4_array 上 qlmc 比 stage-0 慢 2.2×，查出来是**分配器**，不是循环
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_gen_alloc` / IAT 槽 / `opt_all` 的 JCMPI 折叠 / `_emit_ir` 的 JCMPI）

## 一、b4 的 2.2× 差距全部在 push 循环

同一份 `b4_array.qma`，同一台机器，分段计时（`build/b4_split.qma`）：

| 段 | qlmc | stage-0 |
|---|---|---|
| push 200 万次 | **34.8 ms** | 7.6 ms |
| 顺序读 200 万 | 5.3 | 5.9 |
| 跨步读 28.6 万 | 1.4 | 2.3 |

读的两段 qlmc 反而更快，所以问题只在 push。反汇编看循环本身只有 17 条指令，
不该是 45 个周期/次。于是做"同一循环跑两遍"的对照（`build/probe/pf.qma`）：

```
qlmc    首次 push 23.3 ms   第二遍 7.3 ms
stage-0 首次 push  7.4 ms   第二遍 3.8 ms
```

**16 ms 是首次触碰的开销** —— 不是循环，是**页错误**。

## 二、根因：.bss 的页比 VirtualAlloc 的页贵 5 倍

qlmc 的 bump 分配器一直建在 `.bss` 里（`BSS_SIZE = 64 MB`，产物里是个
`vsize=0x4000000`、`rawsize=0` 的节）。`.bss` 是**映像节**，页是 pagefile
后备 + 写时复制；`VirtualAlloc(MEM_COMMIT)` 给的是私有页。本机（VBS 开启）
用 C 直接量三种来源写 16 MB：

| 来源 | 16 MB 顺序写 |
|---|---|
| `static int64_t a[2M]`（.bss） | **21 ~ 29 ms** |
| `malloc(16 MB)` | 5.9 ~ 7.1 ms |
| `VirtualAlloc(MEM_COMMIT)` | **5.7 ~ 6.4 ms** |

每页 5.5 µs vs 1 µs。**提交本身不花钱**（`VirtualAlloc` 16 MB 只要 0.01 ms，
零页是首次触碰时才给的），所以"分块提交"没有意义，一次提交 64 MB 就够。

## 三、改法

`__alloc` 首次调用时向内核要 64 MB（`MEM_COMMIT|MEM_RESERVE`，`PAGE_READWRITE`），
把基址/上限写进 `.bss` 的四个槽：

| bss 偏移 | 含义 |
|---|---|
| 0 | bump 游标（0 = 还没初始化） |
| 8 | 自旋锁 |
| 16 | 堆基址 |
| 24 | 堆上限（基址 + 64 MB） |

- `.bss` 从 64 MB 缩到 **32 字节**（产物节表 `vsize=0x4000000` → `0x20`）。
- 越界检查顺带从 `lea rcx,[bss+16]; add rcx,HEAP_LIMIT; cmp r8,rcx` 收成
  `cmp r8,[rip+bss+24]` —— 少两条指令，而且上限不再是编译期常量。
- 冷路径（`_init`）放在 `ret` 之后：`push rcx/rdx/r9/r10/r11` + 32 字节影子空间
  （5 push = 40，`40+32 = 72`，入口 rsp ≡ 8 → call 时 ≡ 0），因为
  **`VirtualAlloc` 会破坏 rdx/r9/r10/r11**，而 `__str_cat` 这类手写例程是按
  "__alloc 只破坏 rax/r8/rcx"写的。
- IAT 加第 12 个内置槽 `VirtualAlloc`（`I_USER` 11 → 12）。

## 四、顺带：b9_json 里两条纯浪费

反汇编 `jws`（每字节 22 条指令）看到两种死代码：

```
mov r8d, 0x20      ← 常量装进寄存器，随后根本没被读
mov rcx, rsi       ← 只为"约定用 RCX"把值搬一趟
cmp rcx, 0x20
```

1. **JCMP→JCMPI 折叠没有退回使用计数**。`_opt_mark` 是按 JCMP 记的（`b` 是 vreg，
   算一次读），随后折成 JCMPI 时 `b` 槽变成立即数，那条 `OP_CONST` 就成了死代码，
   但 `use[]` 还记着"读了一次"，DCE 不敢删。折叠处补一行 `use.set(b, use-1)`。
2. **比较没必要搬进 RCX**。`cmp r64, imm` 是只读操作数，值在哪个寄存器就比哪个。
   加 `_reg_hint(fc, v)`（返回值当前所在的通用寄存器，不在寄存器返回 -1），
   `OP_JCMPI` 有 hint 就直接 `_cmp_imm(code, rr, imm)`。

`jws` 每字节 **22 → 18 条**（4 条死常量 + 4 条搬运里，常量与 `mov rcx,rsi` 全消）。

## 五、效果（本机 min of 5，两轮交替）

| 基准 | 改前 | 改后 |
|---|---|---|
| b4_array | 31.3 ~ 32.7 | **13.7 ~ 15.9**（−51 ~ −54%） |
| b9_json | 29.2 ~ 30.7 | 27.1 ~ 31.2（噪声内，指令数确实少了） |
| b1_int | 39.0 ~ 44.0 | 41.9 ~ 42.4（噪声内） |

b4 的绝对值还能拆开看：push 段 23.3 → 8.8 ms，其中"首次触碰"从 16 ms 降到 3.7 ms，
剩下的 5 ms 是循环本体（下一步的目标：冷路径沉到函数末尾，热路径只剩一条回边）。

## 六、坑

- **`.bss` 不是"免费的内存"**。以前认为"不占文件体积、按需提交，给足没有代价"，
  但它的页比私有页贵 5 倍 —— 分配密集的程序每个程序启动都在交这笔税。
- `VirtualAlloc` 的 64 MB **提交**几乎不花时间（0.01 ms），花时间的是首次写。
  所以不要按 1 MB 分块提交（那是把一次系统调用拆成 64 次，没有收益）。
- 冷路径保存寄存器时**必须把影子空间算进去**：5 push + `sub rsp,32` 之后
  call 才是 16 对齐；少减 32 会在 `VirtualAlloc` 内部 AV（非确定性，取决于
  kernel32 用了多少 SSE）。
