# v1.70 — Cookie：解析与 Set-Cookie 生成（+ 一个新发现的 Lower 缺陷）

- 日期：2026-10-23
- 任务：§2「静态文件 / MIME / cookie / session / multipart」里的 **cookie** 一块。
- 影响面：标准库（`std/cookie.qma`，全部用 Quelmara 写）、测试、文档、`07-gaps` §7.8

## 新增 API

| 函数 | 说明 |
|---|---|
| `cookie_get(header, name) -> str` | 从 `Cookie:` 头取值；不存在返回空串；同名取第一个；两侧空白忽略 |
| `cookie_has(header, name) -> bool` | 只判存在 |
| `cookie_value_encode(s) -> str` | 非 `A-Za-z0-9-_.~` 字节做 `%XX`；空格是 `%20`（不是 `+`） |
| `cookie_value_decode(s) -> str` | `%XX` 还原；非法序列原样保留 |
| `cookie_attrs(http_only, secure, same_site) -> str` | 拼 `; SameSite=…; HttpOnly; Secure` |
| `cookie_set(name, value, path, max_age, attrs) -> str` | 拼 Set-Cookie 值；空值 + `max_age<=0` 自动写 `Max-Age=0`（删除写法） |

## 为什么 `cookie_set` 是 5 个参数

写第一版时用了 7 个参数（`name, value, path, max_age, http_only, secure, same_site`），
结果**整段程序静默不执行**。二分后定位到一个既有 Lower 缺陷：

> 参数个数 = 7 且**第 7 个是 `str`**（栈上传参），函数被调用 ≥2 次 → 整个 `main`
> 一行都不输出、退出码 0。7 个 int、8 个 int、5 个参数都正常。

已登记 `07-gaps.md` §7.8（附最小复现）。`std/cookie` 因此改成"5 参 + 属性串"，
既绕开缺陷，也把属性拼装拆成独立的 `cookie_attrs`。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/cookie.qma` | **新增**：6 个公开函数 + 3 个内部辅助（`ck_is_unreserved` / `ck_hex` / `ck_hex_val`） |
| `tests/t109_cookie.qma` | **新增**：解析（空值/空白/同名/空头）、编解码（`%20`、`;`、`=`、裸 `%`、非法序列）、Set-Cookie 六种属性组合、删除写法、多次调用互不影响 |
| `tests/run_win_tests.py` | 注册 `t109_cookie` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：51 个模块 / 347 个公开函数 |
| `docs/07-gaps.md` | §2 该行补 Cookie ✅；**新增 §7.8**（7 参 str 缺陷） |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.70.0 |

## 实现要点

- **cookie 值不是 query 参数**：空格编码成 `%20` 而不是 `+`（`+` 在 cookie 里就是
  字面加号），测试钉住了这一条。
- **同名取第一个**：与浏览器行为一致；`cookie_has` 与 `cookie_get` 用同一套切分逻辑。
- **删除 cookie 的标准写法**：`name=; Max-Age=0; Path=/`——值为空且 `max_age <= 0`
  时自动补 `Max-Age=0`，调用方不用记这个约定。
- 十六进制编码直接算字节值（`48+n` / `87+n`），不查表、不切字符串。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t109_cookie.qma` | 25 条断言全过 |
| `python tests/run_win_tests.py` | PASS=201 FAIL=0 SKIP=1（21:25 实测） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（51 模块 / 347 公开函数） |
| 四道门禁 | 全 PASS |
| lexdiff / parsediff / irdiff | **本次未复跑**：另一条轨在 21:27–21:32 修改 `qlm_cli.py` / `qlm_native.py`（调试信息特性），编译器中途不可用（`TypeError: _build_win() got an unexpected keyword argument 'dbg'`）。等对方收口后复跑即可，本版只新增 `std/cookie.qma` 与 `tests/t109_cookie.qma` 两个源文件 |

## 已知边界 / 遗留

- 不做签名/加密（session 层的事）、不校验 Cookie 头长度、不支持 `Partitioned` 属性。
- **§7.8 的 7 参 str 缺陷未修**——它影响的是一整类 API 形状（>6 参且末参是 str），
  值得单开一版查 Lower 的栈传参平衡。
- session / multipart 仍缺（§2 同一行）。
