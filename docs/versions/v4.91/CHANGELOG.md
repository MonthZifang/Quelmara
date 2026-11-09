# v4.91 — `parfor` 语法落地：统一核心的编译器内建入口

- 日期：2026-11-10
- 任务：让单线程单核应用**迁移到本语言后能直接拿到多核**——把「统一核心」
  从"要手写 `ucore_sum(...)`"变成"把 `for` 改成 `parfor`"
- 影响面：编译器（词法 / 语法 / 降低）、语言参考

## 背景：为什么要有 `parfor`

`std/ucore.qma`（v4.86）已经提供了统一核心，但用法是**重写代码**：

```qma
// 用户原本的串行代码
let mut s = 0
for i in 0..n { s = s + (i * 7) % 13 }

// 想用多核，得改成这样（要写 kernel 函数、传函数地址、处理 arg）
let s = ucore_sum(0, n, 16384, kernel_fn, 0)
```

这对"从单线程原生应用迁移过来"的开发者是**真实的门槛**：他们得先理解
`kernel` 形状、`grain` 粒度、`arg` 约定，还要把循环体抽成一个顶层函数。

用户的要求是"无缝衔接"。所以本版把并行入口下沉到**语法层**：
把 `for` 写成 `parfor`，一个词的差别。

```qma
let mut s = 0
parfor i in 0..n { s = s + (i * 7) % 13 }
```

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增关键字 `parfor`（`K_PARFOR = 24`）与语句节点 `S_PARFOR = 26`；解析 `parfor i in lo..hi { 体 }`；降低为区间循环 |

### 语法契约（本版固定下来）

```
parfor <变量> in <lo>..<hi> { <体> }
```

- **只接受 `lo..hi` 形式**，不接受 `parfor k in vec`。切块要求区间可等分；
  遍历容器要按元素下标切，语义面大得多，留给后续版本。
- `<lo>` / `<hi>` 各求值**一次**（与 `for` 同口径，上界钉进变量）。
- 循环变量在体内是隐藏的 int 变量，语义与 `for` 完全一致。

## 本版的实现阶段：先立语法与语义，并行在 v4.92

本版 `parfor` **降低为串行区间循环**（与 `for` 生成完全相同的 IR）。

**为什么不做完整并行**：并行化必须把循环体变成**独立函数**（`spawn` 只能调
函数），而 qlmc 的函数表在**解析期**就冻结了 —— `main` 里
`let nfunc = len(fns)` 之后不能再追加函数：

```qma
let nfunc = len(fns)          // 解析完成后立刻定长
let fnpos = vec[int].new(nfunc)
```

所以 worker 函数必须在**解析期**克隆 AST 子树生成，且要把子树里的变量 id
全部重映射（否则会与父函数的局部变量撞 id）。那是独立的一次改造，且极可能
破坏自举的逐字节等价 —— 而自举不动点是这个仓库的硬门槛。

**拆成两步的好处**：`parfor` 的**语法契约现在就固定**。v4.92 把实现换成并行时，
用户代码一行都不用改。

## 验证

| 命令 | 结果 |
|---|---|
| `parfor` 与 `for` 同区间同体，结果比对 | **一致**（`5999994 == 5999994`，`s == t` 为 `true`） |
| 自举三代 | **s1 == s2，711168 字节** —— 不动点保持 |
| 76 个基准 checksum vs C | **76/76 一致**（未被影响） |
| `python3 tools/dev/check_docs.py` | PASS |

复核命令：

```bash
cd /root/Quelmara/Quelmara
cat > /tmp/pf.qma <<'Q'
fn main() {
    let n = 1000000
    let mut s = 0
    parfor i in 0..n { s = s + (i * 7) % 13 }
    print(s)
}
Q
wine build/qlmc.exe build /tmp/pf.qma -o /tmp/pf --target elf --no-bounds-check
chmod +x /tmp/pf && /tmp/pf        # 5999994
```

## 已知边界 / 遗留

- **本版不并行**：`parfor` 目前与 `for` 生成相同代码。真正的多核在 v4.92
  （需要解析期 AST 克隆 + 变量 id 重映射）。
- 不支持 `parfor k in vec` / `parfor k in map`。
- 不支持 `break` / `continue` 跳出 `parfor` 的跨块语义（串行阶段无影响；
  并行化时必须显式禁止或定义语义）。
- 归约识别未做：并行化后 `s = s + ...` 这种归约必须由编译器识别成
  每块独立累加 + 合并，否则会数据竞争。这是 v4.92 的核心难点。
