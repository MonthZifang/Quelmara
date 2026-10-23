# v1.59 — std/regex：正则引擎（回溯 VM，标准库）

- 日期：2026-10-23
- 任务：07-gaps §2「正则」行 ❌→✅——文本清洗 / 路由匹配 / 表单校验的空缺补上。
- 影响面：`std/regex.qma`（新增，715 行）、`tests/t99_regex.qma`（新增）、
  `tests/run_win_tests.py`（注册）、`tools/dev/gen_stdlib_doc.py`（DESC 登记）、
  `docs/06-status.md`、`tools/stage0/qlm_cli.py`（VERSION）

## 支持子集（与 Python re 差分对拍）

- 字面字节、`.`（除 \n）、字符类 `[a-z0-9]`/`[^...]`（范围 + `\d \w \s` 及大写
  否定式）、转义（`\n \t \r \f \v` 控制类 + `\. \* \( \\` 字面类）
- 量词 `*` `+` `?` `{n}` `{n,}` `{n,m}`（贪婪；无懒惰 `*?`）
- 交替 `|`、分组 `( )` / `(?: )`（**仅分组语义，不捕获**——捕获组留待后续）
- 锚点 `^` `$`（$ 兼容 Python：串尾或串尾单个 \n 之前）

## API（7 个 pub fn）

`regex_compile`（pat -> vec[int] 程序，语法错误返回失败哨兵）/
`regex_match`（搜索，语法错误 -2）/ `regex_match_full`（全匹配）/
`regex_exec` / `regex_find` / `regex_replace` / `regex_replace_all`

## 实现要点

- **Russ Cox 式字节码 + 显式栈回溯**，无 AST：递归下降直接发射到 vec[int]，
  指令变长（CHAR/ANY/BOL/EOL/JMP 2 槽、SPLIT 3 槽、CLASS 34 槽），VM 按 op 步进。
- **病态模式兜底**：VM 步数上限 400 万，超限判不匹配——指数回溯不会挂死进程。
- **单分支不发射 SPLIT**（空分支 = 空匹配语义，v1.59 初版在此错过一次）。
- 空匹配不参与替换（regex_replace_all 跳过，避开 Python 空匹配邻接规则的复杂度）。

## 修复（本版内抓到）

- **悬空量词**：`a|*` 曾把 `*` 当字面量编译成功——`_re_atom` 对 atom 位置的
  `*` `+` `?` 补 fail-fast（返回 -1 -> regex_match 返回 -2）。

## 验证（现跑）

- `tests/t99_regex.qma`：全部断言过（搜索/全匹配/类/量词/交替/分组/锚点/
  替换/负向语法错误），输出 `ok t98_regex`。
- 主回归 **PASS=168 FAIL=0 SKIP=1**（+t99_regex）。
