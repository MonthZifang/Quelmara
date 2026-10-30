# v3.32 — 非 UTF-8 源文件抛裸异常，单源构建还打整段 traceback

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.31 复核时确认仍存在的 §7.11
- 影响面：**工具链**（`qlm.py` 加 `read_source`、`qlm_cli.py` 统一诊断出口），
  新增 `tests/encoding_diag_test.py`
- 版本：按 `00-convention.md` §5.1 建版本目录

## 两个问题

### 1. 非 UTF-8 源文件抛裸 `UnicodeDecodeError`

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 45:
invalid start byte
```

四个问题叠在一起：

* **没有文件名** —— 多文件构建时不知道是哪个文件；
* **没有行号** —— `position 45` 是**字节偏移**，用户得自己数；
* **不是 `SyntaxError`** —— CLI 的错误处理只捕 `SyntaxError`；
* **没有可操作建议** —— 用户不知道该怎么办。

### 2. 单源构建打整段 traceback

因为上面的异常不是 `SyntaxError`，`cmd_build -> build()` 不捕获它，
用户看到的是一整段 Python 栈：

```
Traceback (most recent call last):
  File "qlm_cli.py", line ..., in cmd_build
  ...
  File "qlm.py", line 4692, in parse_file
    text = read_source(path)
SyntaxError: bad2.qma:3:4: 源文件不是合法的 UTF-8 ...
```

有意思的是：**多源并行路径反而是干净的** —— `_build_unit` 里有个
`except Exception` 兜底。于是"单源比多源难读"，这没有任何道理。

## 改法

### `read_source(path)`：统一的源文件读取

放在 `qlm.py` 的 `tokenize` 之前，做三件事：

1. **解码失败 -> `SyntaxError`**，带文件名与 `行:列`
   （用出错字节之前的内容算，不解码整段）：

   ```
   bad.qma:3:4: 源文件不是合法的 UTF-8（字节 0xff 无法解码）。
   常见原因：编辑器按 GBK/ANSI 保存，或存成了 UTF-16。请转成 UTF-8（无 BOM）。
   ```

2. **剥掉 UTF-8 BOM** —— 否则词法器报"非法字符 '\ufeff'"，而用户
   看不出 BOM 在哪。这个坑在写测试夹具时踩过不止一次
   （`Out-File -Encoding utf8` 会加 BOM）。

3. 两处读源码的点都改用它（`parse_file` 与 `_consts_of`）。

### `main()` 统一诊断出口

```python
try:
    return handler(args)
except SyntaxError as exc:
    print(f"[qlm] 编译错误：{exc}", file=sys.stderr)
    return 1
```

**只捕 `SyntaxError`**（语言层的编译错误，**预期内**的失败）。
其它异常仍然抛出去带 traceback —— 那是编译器自己的 bug，
藏起来只会更难查。

## 效果

| 场景 | 改前 | 改后 |
|---|---|---|
| 非 UTF-8 源文件 | 裸 `UnicodeDecodeError` | `bad.qma:3:4: 源文件不是合法的 UTF-8（字节 0xff...）` |
| 语法错误 | 整段 traceback | `[qlm] 编译错误：line 1: 期望 NAME，得到 '{'` |
| 未定义函数 | 整段 traceback | `[qlm] 编译错误：未定义函数 nosuchfn` |
| 类型不匹配 | 整段 traceback | `[qlm] 编译错误：函数 g 的第 1 个形参期望 int，实参是 str` |
| 带 BOM 的文件 | 报"非法字符 '\ufeff'" | 正常编译运行 |

四类错误都是**退出码 1、一行诊断、无 traceback**。

## 夹具

`tests/encoding_diag_test.py`（6 项）：

| # | 判据 |
|---|---|
| 1 | 非 UTF-8 -> `SyntaxError`，消息含文件名与 `行:列` |
| 2 | 带 BOM 的源文件能编译**并运行** |
| 3–5 | CLI 对语法错误 / 未定义函数 / 类型不匹配：一行诊断、无 traceback、退出码 1 |
| 6 | 正常程序：退出码 0、无 traceback |

第 2 项是"能编译并运行"，不只是"能编译" —— BOM 若被当普通字符喂给
词法器，编译期就会挂，所以运行成功才说明真的剥掉了。

已挂进 `run_win_tests.py`（`case_encoding_diag`）。

## 回归

全量 Windows 回归第一次跑**红了一条** —— 而且红得对：

```
[FAIL] 非 UTF-8 被判 rejected
```

`tests/fuzz_test.py:114` 原本断言"非 UTF-8 → **bug**"，注释写着
"编译器读文件时抛 UnicodeDecodeError，属**已知缺陷**"。

我修好了这个缺陷（转成 `SyntaxError`），分类器按自己的定义把它归到
`rejected` —— 那是**设计好的 fail-fast**，断言就红了。

**又是"拿真实缺陷当测试前提"**。与 v3.26 那次（`lsp_test.py` 用
`std/ws` / `std/sse` 当"解析失败"负向样本）同一个模式：测试把
"缺陷存在"编码成前提，修好缺陷反而打红回归。

改成断言 `rejected`，并写明"若又变回 `bug` 说明回退了"。

改完全量 Windows 回归 PASS=350 FAIL=0 SKIP=0（v3.31 是 349，新增 1 条
`case_encoding_diag`）。

## 遗留

§7.11 只覆盖了**主构建路径**。其它入口仍是裸 `open(..., encoding="utf-8")`：

* `qlm_cli.py:248`（`tokfmt` 词法调试工具）
* `qlm_doc.py` / `qlm_dbg.py` / `qlm_dbinfo.py` / `qlm_lsp.py` 等辅助工具

这些不是编译主路径，用户遇到编码问题的概率低得多。要统一收口，
得把这些点也换成 `read_source` —— 属于清理工作，不影响正确性，
留待后续。

**7.6（聚合 `==` 是地址比较）是设计如此**，不是 bug，文档里已说明
"需要按字段/变体手写比较"。

**7.18 / 7.33** 在 qlmc 侧（类型编码方案 / 栈实参布局），是独立工程。
