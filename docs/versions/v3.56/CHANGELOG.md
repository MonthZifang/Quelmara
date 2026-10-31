# v3.56 — `args()` 源码级预置注入；覆盖率 58 → 59

- 日期：2026-11-01
- 任务：用户要求"继续"；补 `args()` 内建（解开 `std/cli`）
- 影响面：`bootstrap/qlmc/qlmc.qma`（`ARGS_PRELUDE` + `_prepend_args_prelude`
  + `_toks_use_args` + `args` 降级 + `_ty_of_expr` 特判）、
  `tests/t200_qlmc_args.qma`、`tests/args_e2e_test.py`、
  `tests/run_win_tests.py`、`tools/dev/qlmc_coverage.py`（`BASELINE` 58 → 59）
- 覆盖率：**58 → 59**（`std/cli`）
- 回归：PASS=369 → **370** FAIL=0 SKIP=0

## 为什么不用 IR 内建

`args()` 要做的事是"取命令行 → 跳过 argv[0] → 按空白/引号切分 → 每段
`mem_str` 成 str → push 进 `vec[str]`"。这是三十多行控制流。

展开成 IR 会撑爆 `_lower_builtin` 的 **416 格帧槽**（那里已经有 21 个内建的
分支），而自举 stage-2 对帧槽极其敏感 —— 这个坑 v3.42 / v3.45 / v3.49
各踩过一次。

## 做法：源码级前置注入

检测到用户源码里出现独立的 `args(` 调用，就把预置实现 lex 成 token，
**拼到用户 token 流的最前面**。对 `parse` 来说它只是普通函数。

```
用户源码 ──lex──> toks
                   ↓
          _toks_use_args(toks)?
                   ↓ yes
    ARGS_PRELUDE ──lex──> pre
                   ↓
          toks = pre(去 EOF) + toks
```

`args()` 本身在 `_lower_builtin` 里降级成一条 `OP_CALL`，目标是
`_qlm_args_impl`。

**为什么用 token 拼接而不是字符串拼接**：Quelmara 的字符串字面量要转义
换行和引号，三十行源码写成一行转义串既难读又容易错（实际调试时我在转义
层级上错了三次）。直接 `lex` 一段常量文本、再把两个 token 流接起来，
源码可以保持原样。

**为什么函数名叫 `_qlm_args_impl`**：`args` 这个名字要留给"识别触发点"。
用户自己定义 `fn args()` 时 `_fn_index` 能找到，走用户函数
（与 stage-0 的 `name not in self.fns_ast` 同口径）。

## 三个踩过的坑

### 坑 1：扫原始文本 vs 扫 token（**破不动点**）

第一版用子串匹配扫原始文本找 `args(`。但 qlmc 自己的源码里有 **9 处**
「注释里写着 `args()`」—— 全被命中，于是**编 qlmc 自己时也注入了预置实现**，
stage-2 与 stage-3 因此不一致，**不动点破**。

改成 `_toks_use_args`：扫 `lex` 之后的 token 流。注释和字符串在 lex 之后
已经不是 `T_NAME` 了，所以看 token 才准。

### 坑 2：`len(args())` 的类型推断

`_ty_of_expr` 对 `E_CALL` 走 `_fn_index(fc, nd.a)` → `fc.fns.get(fi).ret_t`。
但 `args()` 的 `nd.a` 是名字 `args`，函数实体叫 `_qlm_args_impl` ——
`_fn_index(args)` 返回 **-1**，类型推断掉到"未知"，于是
`len(args())` 报 `len() 只支持 str 与 vec`。

而 `let a = args(); len(a)` 正常（走 `fc.vty` 而不是静态推断）——
这种"嵌套调用才失败"的形态最容易漏测。

修法：`_ty_of_expr` 对 `args` 特判返回 `TY_VEC + TY_STR`。

### 坑 3：空串参数

`argv = ["", "empty-first"]` 时 stage-0 给 `n=1`、qlmc 给 `n=2`。

stage-0 的 `__win_args_init` 第一遍数 token 时用 `inword` 标志 ——
两个分隔符之间什么都没有就不产生 token。我的实现是"跳到非空白 → 收字符"，
空串位置会收出长度 0 的串。

修法：`out.push` 之前判 `blen > 0`。

## 测试

`tests/t200_qlmc_args.qma` + `tests/args_e2e_test.py`，注册为
`case_args_e2e()`。PASS=10。

Python 端用 `subprocess` 直接传 argv（不经过 shell），逐字比对 stage-0 与
qlmc 的输出。7 组 argv：空表 / `--out x.exe` / 含空格 / `--flag=value` /
单个 / **空串参数** / 5 个参数。

**一个反直觉的期望值**：Windows 的 `GetCommandLineA` 会把带引号的参数
原样返回（含反斜杠），所以 `'"a b"'` 这个 argv 元素在**两边**都解析成
`\a` / `b\` 两个 token。这不是 bug —— stage-0 也是这样（已实测）。
所以测试不写死"正确"的期望值，而是拿 stage-0 当基准做差分。

## 覆盖率

`std/` **58 → 59**：`std/cli.qma` 解锁。`BASELINE` 已上调到 59。

剩余 11 个模块：

```
2  缺内建: xmm_load           (std/aes, std/tls13)
2  未知类型 TlsClientResult   (std/httpc_net, std/tls_net)
1  vec[vec[T]] §7.18          (std/csv)
1  泛型 [T: Ord]              (std/gen)
1  函数重复定义 _fail         (std/http)
1  函数重复定义 _get          (std/logfile)
1  缺内建: syscall            (std/park_linux)
1  结构体字面量含方法调用      (std/session)
1  缺内建: xmm_mov            (std/tls_client)
```

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 646656 B，仍在 `ARENA_CAP = 4 MB`
余量内。

## 方法教训

这一版在**转义层级**上错了三次（`\\\\n` vs `\\n` vs `\n`）—— 每次都要
重编 2.5 分钟。最后靠 `_peek_prelude.py` 打印 `repr()` 才看清实际字符。

**教训**：改字符串常量里的转义序列时，先用 `repr()` 看清实际内容，
不要靠肉眼数反斜杠。
