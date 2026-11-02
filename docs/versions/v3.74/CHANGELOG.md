# v3.74 — irdiff 的 `target_arch` 归一化漏了常量折叠后的形态

- 日期：2026-11-02
- 任务：v3.73 推送后 CI 在 linux 的「发射层确定性」上红了一条：
  `tests/t184_qlmc_strptr.qma` 被判 x86/a64 分叉。
- 影响面：`tests/irdiff.py`（约 10 行）
- 代码改动：约 10 行

## 真因：不是 qlmc，是门禁自己的归一化规则不完整

v3.19 加 `target_os()` / `target_arch()` 时补过一条归一化：这两个内建
**按定义就取决于目标**，所以把它们折叠出的立即数抹成 `T` 再比对。
但那条规则只匹配 `jcc` 的「两个 imm 比较」形态：

```python
('jcc', 'ne', ('imm', 1), ('imm', 2), ...)
```

而 `t184` 里是 `assert(target_arch() == 1, ...)`，优化器的**常量折叠**
会把它直接折成单 imm 的分支：

```
x86: ('jnz', ('imm', 1), 'main.assert_ok.12')
a64: ('jnz', ('imm', 0), 'main.assert_ok.12')
```

于是绕过了归一化，被判分叉 —— 但那是**正确行为**：a64 上
`target_arch()` 返回 2，`2 == 1` 本来就该折成假。测试里那句
「qlmc 只产 x86-64，target_arch 恒为 1」只对 x86 后端成立。

## 修法

`normalize()` 补一条 `TARGET_JNZ_RE`，把折叠后的
`('jnz'|'jz', ('imm', N), L)` 也归一化成 `T`：

```python
TARGET_JNZ_RE = re.compile(r"\('(jnz|jz)', \('imm', \d+\),")
...
s = TARGET_JNZ_RE.sub(lambda m: f"('{m.group(1)}', ('imm', T),", s)
```

## 为什么之前没暴露

上一次 CI（v3.59，`41236055596`）在**门禁步骤**就红了，根本没跑到
irdiff 这一步。所以这条分叉一直藏着，v3.73 修好门禁后才露出来。

## 验证

| 命令 | 结果 |
|---|---|
| `check_one('tests/t184_qlmc_strptr.qma')` | ✅ `bad` → `ok` |
| `python tests/irdiff.py`（全量） | ✅ **PASS=121 FAIL=0 SKIP=110**（此前 120/121） |

## 顺带记录：CI 里另一条失败与本版无关

同一次 CI 的 windows 上 `WS_E2E: PASS=16 FAIL=1`。本地跑
`python tests/ws_e2e_test.py` 是 **17/17 全过**；而且 v3.73 那次提交
**完全没有改动 `std/` 与 `tests/ws_e2e_test.py`**（`git diff 4e901f9 HEAD`
在这两个路径上是空的）。判定为网络时序偶发，不是回归。
