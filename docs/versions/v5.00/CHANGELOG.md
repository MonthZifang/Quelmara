# v5.00 — 堆上限从编译期常量改为可配置（`--heap-mb`）

- 日期：2026-11-05
- 任务：用户要求"内存上限可设置，用户可以在配置文件里决定，
  或在代码里对单个程序/目录/进程设限，而不是全局写死"。
- 结论：**已实现** `--heap-mb N`。

## 改之前是什么样

`bootstrap/qlmc/qlmc.qma` 里写死：

```quelmara
const HEAP_SIZE = 0x10000000      // 256 MB
```

三处用它，**全部是 imm32 立即数**：
1. PE 的 `VirtualAlloc` 的 `mov edx, HEAP_SIZE`
2. ELF 的 `mmap` 的 `mov esi, HEAP_SIZE`
3. 上限计算 `lea r8, [rax+HEAP_SIZE]`

而 `Quelmara.toml` 里**早就有** `[memory] heap_limit_mb = 512`
—— 但 qlmc 根本没读它（`qlmc` 没有配置解析器，第 18162 行的注释明说这件事）。
于是"配置文件里写了 512"和"实际 256"长期不一致。

## 改了什么

新增全局状态 `SW_HEAPMB` + 命令行 `--heap-mb N`（1..65536）：

```quelmara
fn _heap_bytes() -> int {
    let mb = _cur_heap_mb()
    if mb <= 0 { return HEAP_SIZE }        // 没设就用默认
    let b = mb * 1048576
    if b > 2147483647 { return 2147483647 } // imm32 上限
    return b
}
```

三处 `HEAP_SIZE` 全改成 `_heap_bytes()`。

## 一个必须一起改的地方（差点漏掉）

第 3 处 `lea r8, [rax+HEAP_SIZE]` 是**上限**计算。只改前两处（mmap 大小）
而不改这里，会变成"只映射 1 MB，但上限仍按 256 MB 判" —— 越界检查形同
虚设，直接 SIGSEGV 而不是干净退出。

实测确认了这个坑：改前 `--heap-mb 1` 跑 100 万元素 → `SIGSEGV`；
三处全改后 → **exit 3**（干净 OOM）。

## 验证

```bash
qlmc build app.qma --target elf --heap-mb 1   -o a   # 100万元素 -> exit 3
qlmc build app.qma --target elf --heap-mb 256 -o b   # 100万元素 -> 1000000, exit 0
```

自举五级链 42/42 + 不动点 PASS。

## 还没做的

* **配置文件读取**：`Quelmara.toml` 的 `[memory] heap_limit_mb` 还没接进
  qlmc（缺 toml 解析器）。目前只有命令行。
* **代码内按作用域设限**（`mem_limit(n)` 对单函数/单 vec 生效）——需要
  重新设计分配器为 arena/区域化，是更大的工程。
* vec 内联布局 / 寄存器分配改进 / SIMD —— 本轮未动。
