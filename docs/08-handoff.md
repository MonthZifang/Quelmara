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
| `std/csv` | `vec[vec[T]]` 类型码撞区间 | **高** | 见 `07-gaps.md` §7.18（已量化） |
| `std/gen` | qlmc **完全没有泛型** | **高** | 见 `07-gaps.md` §7.44（已量化） |

**只剩两个，都是"专门版本"级的架构工作。** 两个都已把**改动面量化**写进
`07-gaps.md`，动手前先读那两节 —— 里面列了检查清单和"为什么不能走捷径"。

**§7.18（`vec[vec[T]]`）的核心难点**：`TY_VEC` 有 23 处引用，其中 8 处是
**区间判断**（`>= TY_VEC && < TY_xxx`），依赖类型码的全序排列。
"把 `TY_VEC` 搬到高位"会让这 8 处**静默失效** —— 这是最容易想到、
也最容易踩的方案。正解是改成"类型表下标"，但那要求 `TY_MAP` 的 K/V
同步改造，**是一次类型系统重构**。

**§7.44（泛型）的真实状态**：不是"支持不完整"，而是 parser 里**根本没有
泛型语法** —— `fn 名[` 直接报"期望标点 #1"。要从零造单态化 + 约束检查。

**两者有耦合**：`vec[T]` 一旦要支持嵌套就同时踩 §7.18，所以做泛型时
`std/gen` 里凡是 `vec[T]` 的形状仍会失败。**建议先做 §7.18。**

> `std/park_linux` **不在这个表里**（v3.63 修正）：它用 `syscall`，
> 在 Windows 目标是声明期硬失败，**stage-0 同样编不过** ——
> 它不是 qlmc 的缺口，而是"本来就不产出 Windows 产物"。
> 覆盖率工具的分母已排除它（见 `PLATFORM_SPECIFIC`），
> 那个排除表**带自检**，编得过的模块塞不进去。

### 已经打通的两种"跨模块"能力（别再重新踩）

| 能力 | 版本 | 做法 | 易错点 |
|---|---|---|---|
| 跨模块 **类型**可见 | v3.61 | import 图**拓扑排序**，被依赖的先 parse | Kahn 方向搞反**不会崩**，只会静默错序 |
| 模块**作用域**（同名私有声明） | v3.62 | `stt` 尾部三个模块号区 + 两趟解析 | **给 `P`/`Fn` 加字段是陷阱**（读出来是垃圾），见 §4.7 |

> 跨模块**同名但签名不同**的声明（`_fail` 有两种签名、`_Ck` 有两种布局）
> 是**静默错编**的形状：不崩不报错、只是结果错。改这块必须有差分夹具
> （`s38_modscope` 是样板）。

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

### 4.7 给核心 struct 加字段是最贵的改动（v3.62 实测）

`P`、`Fn`、`FnCtx`、`Node` 这些是 qlmc **自身**的高频 struct。
往它们里面加字段，症状可能完全不像"字段问题"：

```
fe.mod   = 131151930794504     ← 一个地址值
p.mod_id = 131151930794504     ← 同一个地址，而且同一函数里两次读还不一样
```

排查顺序（照这个走，别跳）：

1. **8 字段 / 16 字段的普通 struct** —— 正常；
2. **`vec[Struct]`** —— 正常；
3. **15 个形参** —— 正常；
4. 加打印才看见 `fe.name=0` 但 `mod` 是地址 → **不是字段值错，是整条记录错位**。

**结论**：换成"不动任何既有 struct、把新数据塞进已有容器的空余区"
（v3.62 用的是 `stt` 尾部三个区）之后一次通过。

**规则**：要在核心 struct 上加字段前，先问"能不能塞进已有 vec 的尾部"。
省下的不是一次重建（约 10 分钟），是**十几次重建的排查时间**。

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
