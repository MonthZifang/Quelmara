# v3.35 — v3.31 的类型检查抓出 stage-1 parser 的真实 bug

- 日期：2026-10-30
- 任务：用户要求"继续"；按 v3.34 新增的 §0 规范，转向 `bootstrap/`
  （核心代码），从"语法：声明级 对拍失败"这条缺口入手
- 影响面：**核心（Quelmara 源码）** `bootstrap/parser/qlm_parse.qma` 三行修复；
  自举状态"语法"从**对拍失败**变成**对拍通过**
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：一条一直红的对拍

`tools/dev/selfhost_status.py` 一直显示：

```
语法   stage1  bootstrap/parser/qlm_parse.qma  就绪  声明级 对拍失败
```

跑 `tests/parsediff.py` 立刻看到原因 —— **v3.31 加的类型检查把它拦下来了**：

```
[qlm] 编译错误：函数 dec_val 的第 1 个形参期望 str，实参是 int
（v3.31 起调用点做标量类型比对；这以前会静默按位重解释）
```

也就是说：**stage-1 parser 从 v3.31 起就编不过了**，但没人发现 ——
因为主回归里跑的是 `bootstrap_test.py` 的另一部分，这条对拍只在
`selfhost_status.py` 里跑，而那个脚本不是门禁。

## 根因：多套了一层 `dec_val`

`bootstrap/parser/qlm_parse.qma` 里数字字面量的处理：

```quelmara
if len(t) > 1 && t[0] == 48 && (t[1] == 120 || t[1] == 88) {
    return "(num " + dec_val(radix_val(strip_us(substr(t, 2, len(t) - 2)), 16)).to_str() + ")"
}
```

`radix_val(t, base)` 已经把 `"ff"` 这类字符串**解析成数值**（返回 `int`），
外面再套一层 `dec_val`（把字符串解析成数值）是：

1. **类型错**：`dec_val` 要 `str`，`radix_val` 给 `int`；
2. **逻辑错**：即使类型对（把 int 当 str 读），也是在解析一个数值的
   字节表示，结果完全是垃圾。

实测确认 `radix_val` 返回值正确：

```
radix_val("ff", 16) = 255
radix_val("10", 2)  = 2
radix_val("17", 8)  = 15
```

所以正确写法是直接输出它：

```quelmara
return "(num " + radix_val(strip_us(substr(t, 2, len(t) - 2)), 16).to_str() + ")"
```

三处（`0x` / `0b` / `0o`）都改。

## 结果

```
[parsediff] 跳过 17 个文件（stage-1 未支持 interface/impl/泛型）：...
--------------------------------------------------------
PASS=234 FAIL=0（共 234 个源文件）
```

自举状态：

```
语法   stage1  bootstrap/parser/qlm_parse.qma  就绪  声明级 对拍通过
```

从"对拍失败"到"对拍通过"。

## 这件事的意义：类型检查真的有用

v3.31 加调用点类型比对时，我写的是"保守推断，宁可漏报不误报"，
并且验证了"不误伤"（70 个 std 模块 + 全量回归全绿）。

这一版证明了另一半：**它确实能抓到真 bug**。而且抓到的这个 bug
有双重性质 —— 不只是类型不匹配，`dec_val(radix_val(...))` 的
**语义本身就是错的**（把数值再解析一遍）。

如果只看类型，可能会想"加个 `to_str()` 绕过去"；看了语义才知道
是多余的嵌套，直接删掉才对。

## 顺带做的核查

用同一个类型检查扫了一遍其余核心代码，确认没有同类问题：

| 范围 | 实参类型错误 |
|---|---|
| `bootstrap/**/*.qma` | **0** |
| `examples/**/*.qma` + `tests/**/*.qma` | **0** |

所以这个 bug 是孤例，不是系统性问题。

## 一个流程问题（本版一并修了）

**`selfhost_status.py` 不是门禁。** 它显示"对拍失败"很久了，
但没有任何 CI 或回归会因为它红 —— 所以 stage-1 parser 编不过
这件事被隐藏了至少 4 个版本（v3.31 引入类型检查到现在）。

已把 `tests/parsediff.py` 接进 `run_win_tests.py` 的 `test_qlmc()`
（与"自举五级链"同一处）。代价约 6 秒（编译 234 个源文件），可忽略。

教训与 v3.14 那条同源：

> 一条从不影响退出码的告警迟早等于不存在。

`selfhost_status.py` 是个**给人看的状态面板**，不是门禁。面板上的红字
如果没人看，和不存在没区别。

## 回归

全量 Windows 回归 PASS=351 FAIL=0 SKIP=0（v3.34 是 350，新增 1 条
`stage-1 parser 声明级对拍`）。

## 遗留

自举仍是 **2/9 组件**（词法、语法完成；类型推断、AST→IR、优化、
x86_64 编码、ELF/PE 写出、AArch64 未做）。

按 §0 规范，后续核心工作应继续在这个方向。下一个自然的入手点是
**AST→IR**（`bootstrap/ir/`，已有对拍骨架）—— 它是"能编译"到
"能生成机器码"的必经环节。
