# v1.45 — qpm semver：区间解析 + git tag 版本选择（工具链）

- 日期：2026-10-23
- 任务：工具链 §3 包管理行 🟡 收窄——semver 区间落地（`^1.2.0` / `~1.2` /
  `>=1.0, <2.0` / `1.2.x` / `||`），git 依赖按区间从远端 tag 选最新满足版本；
  同步修复 `path:` / `git:` 前缀 spec 的文档/实现不一致（v0 只实现了前缀探测，
  文档写的前缀形式实际不可用）。
- 影响面：工具链（tools/qpm.py、新增 tools/qpm_semver.py、新增
  tests/qpm_semver_test.py）、文档（05-toolchain / 07-gaps）

## 为什么是它

§3 包管理是唯一"已有实现、缺版本语义"的行：qpm v0 只能锁精确 tag/branch/sha，
依赖方无法声明"要 1.x 的最新兼容版"——升级依赖 = 手查 tag、手改 toml、手跑
install。semver 区间是 registry / 发布流程的前置：没有"声明-解析-锁定"的
闭环，registry 只是换个地方存 tag。

本轮不动编译器与语言层（与并行的语言层工作零文件重叠），纯工具层推进。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/qpm_semver.py` | **新增**（纯标准库）：Version（semver.org §11 全序，build 不参与比较）；区间解析与展开（`^` `~` `=` `>` `>=` `<` `<=`、通配段、部分版本的 node 语义、AND/OR）；预发布门槛（带预发布的版本只满足"同 X.Y.Z 且带预发布的比较符"所在 AND 组）；`max_satisfying` / `parse_tag` / `select_tag` |
| `tools/qpm.py` | `parse_spec`：显式 `path:` / `git:` 前缀（与 v0 前缀探测等价，文档口径统一）；`_looks_like_range`：语法式区间判定（运算符开头/分隔符/通配段，纯版本串仍按精确 tag——v0 语义）；`ls_remote_tags`；`resolve_one` 区间分支：ls-remote → 选最新满足 tag → 收敛 rev 后走 v0 clone/缓存/复制路径，无满足 tag 时 fail-fast 并列出可用 tag；锁文件格式不变（`kind\|src\|rev\|sha`，区间依赖的 rev 是解析后的 tag） |
| `tests/qpm_semver_test.py` | **新增**：单测（§11 全序链 / build 忽略 / 非法输入 / 区间 30 例 / 预发布门槛 / max_satisfying / select_tag）+ 端到端（file:// 本地 git 六种区间形态 → 断言锁与副本布局；无满足 tag fail-fast；`path:` 前缀）。夹具 `.git` 不入库，测试按 `.gitignore` 注释"演示时重建"自愈 |
| `tools/stage0/qlm_cli.py` | VERSION 1.44.0 → 1.45.0 |
| `docs/05-toolchain.md` | §4 重写 spec 形态与锁定语义；删"未做 semver"；§8 删过期断言（version 命令早已打印 VERSION，不再固定 1.0.0） |
| `docs/07-gaps.md` | §3 包管理行、§6 P1-7、§8 第 4 项同步（semver ✅ v1.45，仍缺 registry/发布/传递依赖冲突） |

## 实现要点

- **区间判定是语法式的**：`#rev` 里含运算符/分隔符/通配段才算区间，纯版本串
  （`1.0.1` / `v1.0`）按精确 tag——名为 `1.0` 的 tag 不会被误读成区间。代价：
  名字恰好长得像区间的 tag（如 `1.x-dev`）会被当区间解析，失败即报错（已登记）。
- **`>` 带部分版本时末位 +1**（`>1.2` → `>=1.3.0`）、`<` 补 0、`<=` 转 `<`
  （`<=1.2` → `<1.3.0`）：与 node-semver 一致，避免"写 `>1.2` 却匹配 1.2.5"的
  反直觉。
- **预发布门槛**：`^1.2.3` 选不中 `2.0.0-rc1`，`*` 也选不中 `1.0.0-rc1`；
  要预发布须显式写（`^1.2.3-rc1`）。稳定版默认不被 rc 突袭。
- **无满足 tag = fail-fast**：报错列出远端全部可用 tag，不静默回落默认分支。
- **锁文件向后兼容**：v0 锁（`kind|src|rev|sha` 四段）照常解析；区间依赖的
  rev 记录解析后的 tag，区间文本留在 Quelmara.toml——`qpm list` 两处对照可读。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/qpm_semver_test.py` | PASS（单测 + file:// 端到端六种区间 + fail-fast + path: 前缀） |
| `python tests/run_win_tests.py` | PASS=155 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，本机沙箱拦，正常） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |
| `python tools/dev/check_docs.py` | PASS |

> 主回归与编译器无关（本轮零编译器改动）；对拍四件套不涉及（无 parser/后端
> 改动），未跑。

## 已知边界 / 遗留

- registry、发布/上传流程、传递依赖冲突合并仍未做（§3 包管理行保持 🟡）。
- 只认整段 tag（可选 `v` 前缀）；`pkg-v1.2.3` 这类前缀 tag 不解析。
- 预发布数字标识允许前导零（`1.0.0-01` 按数值 1 比较）——选 tag 不做语义警察。
- 区间/精确判定语法式：名为 `1.x-dev` 的 tag/branch 会被当区间解析并报错，
  暂无转义写法。
- `qpm outdated`（对照最新满足版本）未做——需要每次 install 都 ls-remote，
  收益/成本不成立，留到 registry 轮。
