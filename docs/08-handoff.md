# 交接文档（HANDOFF）

> 这份文档面向"接手继续做"的人，只写**现在在哪、下一步做什么、有哪些坑**。
> **实测数字一律不写在这里**，见 [`06-status.md`](06-status.md) —— 数字只允许
> 出现在 `06-status.md` 与各版本 `CHANGELOG.md`（`00-convention.md` §4）。

## 1. 一句话现状

`bootstrap/qlmc/qlmc.qma`（用 Quelmara 写的 stage-1 编译器）能编译的
`std/**/*.qma` 模块数，是这条轨道唯一的硬指标。当前值、基线、剩余缺口
见 [`06-status.md`](06-status.md)；缺口清单与难度分级见
[`07-gaps.md`](07-gaps.md)。

门禁（会拦住退化的）：

```bash
python tools/dev/qlmc_coverage.py       # 覆盖率不得低于 BASELINE
python tests/bootstrap_test.py --strict # 自举五级链 + 不动点
python tests/qlmc_test.py               # stage-0 vs qlmc 逐字节差分
python tools/dev/check_docs.py          # 文档漂移 / 数字单一来源
```

## 2. 上手先跑这四条

```bash
cd <repo>
git log --oneline -3                    # 确认接的是哪一版
python tools/dev/check_docs.py          # 文档门禁（最容易被忽略）
python tests/bootstrap_test.py --strict # 自举是否还成立
python tools/dev/qlmc_coverage.py       # 覆盖率有没有退化
```

四条全绿再动代码。**改 `std/` 之后必须补跑**
`build <夹具> --target native` 与 `--target arm64` —— 主回归在 Windows 上，
覆盖不到 ELF 后端（v3.15 就是这么把 CI 打红的，见 §4.6）。

## 3. 剩余缺口（按性价比排序）

| 模块 | 缺口 | 难度 | 备注 |
|---|---|---|---|
| `std/httpc_net` | `struct 重复声明 _Ck` | 中 | **与下三行同一个根因**：qlmc 缺 per-module mangling |
| `std/http` | 函数重复定义 `_fail` | 中 | 同上 |
| `std/logfile` | 函数重复定义 `_get` | 中 | 同上 |
| `std/csv` | `vec[vec[T]]` 类型码撞区间 | **高** | 架构性，见 `07-gaps.md` §7.18 |
| `std/gen` | 泛型 `[T: Ord]` | **高** | 需要单态化 |
| `std/park_linux` | `syscall` 内建 | 低 | **Linux 专用**，Windows 上意义有限 |

**建议顺序**：**per-module mangling**（一次解 3 个模块）→
最后三个大件各留给专门版本。

`std/httpc_net` / `std/http` / `std/logfile` 三条**不是三个问题，是一个**：
qlmc 不做 `pub` 可见性检查，于是不同模块里的同名私有声明（`_Ck` 结构体、
`_fail` / `_get` 函数）被当成同一个名字。stage-0 按 `pub` 做 per-module
mangling（v1.99），qlmc 没有。修法见 `07-gaps.md` §7.43。

**注意性能约束**：`_struct_index` / `_fn_index` 都在热路径上（每次类型
解析、每次调用都查），加一维不能退化成 O(n²) 全表扫。

> 跨模块 **struct 类型**本身已经能用了（v3.61 的 import 图拓扑排序），
> `std/tls_net` 就是靠它解开的。剩下的只是**同名**问题。

## 4. 必读：这个项目反复踩的六个坑

这些都是**用整版时间换来的教训**，接手时务必先读。

### 4.1 帧槽 416 上限

`_lower_builtin`、`_emit_ir`、`build_rdata`、`main` 这些大函数**贴着 416 槽上限**。
往它们里面加任何代码，都可能让自举 stage-2 编不过自己。

**规则**：给这些函数加逻辑前，先抽独立函数。加完立刻跑
`python tests/bootstrap_test.py --strict`。`_lower_simd_extra` 就是这么抽出来的。

### 4.2 常量编号撞车

- `I_CREATE` 其实是 `CreateThread`
- `_op_name` 表错位
- `S_FOREACH` 撞 `S_BREAK`

**规则**：加新 opcode / IAT 槽 / 语句编号后，用
`grep '^const S_'`（或 `OP_` / `I_`）**全表核一遍**。编号区间不连续，
"看着空"不等于真的空。`build/_opscan.py` 可以扫空缺。

### 4.3 静默错编（最难抓）

不崩、不报错、结果错。典型例子：

- `map.del` 直接清键 0 → 切断探测链 → 后面的键**找不到但数据还在**
- 端口字节序拆反 → `sendto` 返回正常但包发错端口
- `_len_of` 缺 SIB 字节 → 只在寄存器分到 R12 时崩
- SIMD 编码 map 写错（`0F 3A` 写成 `0F 38`）→ 完全是另一条指令，静默算错

**规则**：改语义的改动**必须有差分测试**（stage-0 vs qlmc 逐字节比），
"能编过"说明不了任何事。

### 4.4 `_ir_emit` 的 `a` / `b` 必须是合法 vreg

`_ir_emit` 里 `if a > 0 { fc.vend.set(a, i) }` —— 塞槽号 / 操作码 / 立即数
会直接 `vec index out of bounds`。

**规则**：额外数据全部塞 `imm`（它不参与 vend 写入）。

### 4.5 诊断粒度

怀疑某个函数时，**在函数体内逐句打点**，不要只在入口/出口打 ——
入口打点只能证明"进来了"，证明不了"哪一句炸的"。

### 4.6 验证矩阵少一格，那一格就烂掉

主回归全绿 ≠ CI 全绿。CI 的 `run_native_tests.sh`（Linux/a64）里有主回归
不跑的东西。**改 `std/` 里任何带 `@ffi` 或 `syscall` 的东西之后**，务必手动跑：

```bash
build <夹具> --target native
build <夹具> --target arm64
```

`@ffi` 是**后端专属的硬失败**：别往共享的 `std/` 模块里直接放 `@ffi`，
否则所有 import 它的非 PE 后端全部编不过。要么拆成独立模块让调用方显式
import（`std/park` / `std/park_linux`），要么用 `static_word` + 函数指针注入
（`std/sync` 的 `sync_set_park`）。

## 5. 工作流约定

### 5.1 一个版本 = 一次完整流程

```
改代码 → 重建 qlmc
       → 验证功能
       → python tests/bootstrap_test.py --strict（必须全 PASS + 不动点）
       → 写差分夹具 + 注册进 tests/qlmc_test.py
       → python tests/run_win_tests.py（全量回归）
       → 文档门禁（check_names / check_origin / check_docs / gen_stdlib_doc）
       → 写 docs/versions/vX.Y/CHANGELOG.md
       → 改 VERSION + 上调 BASELINE（如果覆盖率涨了）
       → 更新 docs/06-status.md（加 §3.10x 小节）
       → 提交 → 推送 → 验证 TREE MATCH
```

### 5.2 数字的单一出处

**实测数字只能写在两处**：`docs/06-status.md` 与 `docs/versions/*/CHANGELOG.md`。
其它文档（包括本文）必须写"见 `06-status.md`"。`check_docs.py` 会拦住违规。

### 5.3 提交与推送

提交时用 `git -c core.safecrlf=false commit`，否则 LF/CRLF 警告刷屏。

**推送有三条路，按可用性选**：

| 方式 | 命令 | 前置 |
|---|---|---|
| SSH | `git push` | 仓库里配了对应私钥 |
| HTTPS + 凭据助手 | `git push https://github.com/<owner>/<repo>.git master:master` | `gh auth setup-git` 或 credential helper 已配 |
| Git Data API | `build/push_via_api.py <parent_sha> HEAD` | `gh auth token` 可用 |

API 建的 commit SHA 与本地不同（committer 由服务端填）**是正常的**，
只要 tree 一致就对 —— 用 `build/_verify_push.py` 验证。

**诊断推送为什么失败（别被退出码骗了）**：

```bash
git ls-remote https://github.com/<owner>/<repo>.git master    # 拉：无需认证
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://github.com/<owner>/<repo>.git/info/refs?service=git-receive-pack"
```

第二条返回 **401 就是缺凭据**（拉能成功、推不行）。另外：

- `git push` 挂住不返回、`timeout` 给出 **124** —— 是在等凭据输入，
  **不是网络问题**。`GIT_TERMINAL_PROMPT=0` 也拦不住 credential helper。
- `git push ... | tail -5; echo EXIT=$?` 里的 `$?` 是 **`tail` 的**退出码，
  永远是 0。**必须把 git 单独重定向到文件再取 `$?`**，否则会误以为推送成功。
- 推送后**一定用 API 或 `ls-remote` 核实远端 SHA**，不要相信本地退出码。

> 2026-11-01：本机环境（Linux 容器）**没有任何 GitHub 凭据**
> （`gh` 未安装、`~/.ssh` 无 GitHub key、无 `GITHUB_TOKEN`），
> 所以 v3.60 / v3.61 两个提交**只落在本地**。接手时先 `git log` 对一下
> 远端 SHA，缺的用上面任一条路补推。

### 5.4 已知的偶发失败

`tests/debugger_test.py` 的"[3] 调试信息不改变程序行为"偶尔 FAIL
（`r1.stdout != r2.stdout`）。根因是 `build_demo(dbg=True)` 可能回退到
`_build_dbg_direct()`（两条构建路径）。**与编译器改动无关**，重跑通常就好。

## 6. 有用的脚本（`build/` 下，都是临时工具）

| 脚本 | 用途 |
|---|---|
| `push_via_api.py` | 推送（SSH 不通时的备选） |
| `_verify_push.py` | 验证远端 tree == 本地 tree |
| `_opscan.py` | 扫 OP 编号空间，找空缺（避免撞车） |
| `_opnames_check.py` | 检查 `_op_names_str` 条目数 |
| `_fnuse3.py` | 量每个函数的 arena 用量（查"编译缓冲不够"） |
| `_scan_args2.py` | 定位源码里所有 `args(` 命中 |

这些都是**一次性诊断脚本**，可以随时删或重写。
