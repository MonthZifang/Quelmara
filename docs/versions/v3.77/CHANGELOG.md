# v3.77 — const 名直接当方法接收者：stage-0 不内联（收 §7.41）

- 日期：2026-11-02
- 任务：收 §7.41（v3.50 发现，一直靠"先存变量再 `.to_str()`"绕过去）。
- 影响面：`tools/stage0/qlm.py`（`parse_primary` 的 const 内联判据）、
  `tests/t194_qlmc_syntax.qma`（去掉绕法，让夹具成为回归钉）
- 代码改动：约 20 行

## 症状

```quelmara
const A = 64
fn main() {
    print(A.to_str())     // ✗ 编译错误：未定义变量 A
    let x = A
    print(x.to_str())     // ✓
}
```

**同一个常量，两种写法行为不同。** qlmc 没有这个问题 —— 所以这是
**stage-0 的缺陷**，方向是修 stage-0，而不是把 qlmc 改成一样错
（否则等于把一个语言缺陷固化进自举链）。

## 真因：`.` 的判据把"路径"和"方法调用"混为一谈

`parse_primary` 里 const 内联的条件是：

```python
if t.val in self.consts and not (
        self.at("SYM", "(") or self.at("SYM", ".")):
    return self.consts[t.val]
```

只要看到 `.` 就不内联 —— 因为 `A.b` 可能是**命名空间路径**（如
`net.Action.Keep`），那时 `A` 不是值。但 `A.b(...)` 是**方法调用**，
`A` 是接收者，必须内联。

下面的 `while` 循环其实已经区分了这两种形态（遇到 `.NAME(` 就 `break`），
只是**上面的内联判据没有用同一个判据** —— 两处逻辑不对称。

## 修法：让内联判据与 `while` 循环的判据对称

```python
if t.val in self.consts:
    is_call = self.at("SYM", "(")
    is_path = False
    if self.at("SYM", ".") and self.peek(1).kind == "NAME":
        nxt2 = self.peek(2)
        if not (nxt2.kind == "SYM" and nxt2.val == "("):
            is_path = True
    if not (is_call or is_path):
        return self.consts[t.val]
```

判据：`.` 之后是 NAME 且**再之后不是** `(` → 路径，不内联；否则内联。

## 顺带：把绕法从夹具里去掉

`tests/t194_qlmc_syntax.qma` 原来被迫写成：

```quelmara
// 不能写 SC_BATCH.to_str()，stage-0 会报"未定义变量"
let batch = SC_BATCH
print("c9=" + batch.to_str())
```

改成直接 `SC_BATCH.to_str()`。**这条用例本身就是缺陷的回归钉** ——
以后谁再把 const 内联的判据写窄，这里会立刻编不过。

## 验证

| 判据 | 结果 |
|---|---|
| `A.to_str()` | ✅ `未定义变量 A` → 输出 `64` |
| 路径形态 `Action.Keep` / 枚举 match | ✅ 不受影响 |
| `P { x: N }`（const 作字段值） | ✅ `32` |
| `N * 2`（const 参与运算） | ✅ `64` |
| `t194` stage-0 与 qlmc 逐字节一致 | ✅ IDENTICAL |
| 全套差分 | ✅ **45/45** |
| irdiff | ✅ **121/121** |

> **这类缺陷的形状值得记**：同一个语义在两条代码路径上用了**不一致的判据**
> （内联判据排除了 `.`，而下面的循环已经会区分 `.NAME` 与 `.NAME(`）。
> 修法不是"再加一个特例"，而是让两处用同一个判据。
