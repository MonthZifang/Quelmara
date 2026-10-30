#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源文件读取：编码错误转成友好诊断（v3.33）。

## 为什么单独一个模块

`read_source` 原本写在 `qlm.py` 里（v3.32）。但**读源码的不止编译器**：

| 模块 | 用途 |
|---|---|
| `qlm.py` | 编译主路径 |
| `qlm_doc.py` | 文档生成 |
| `qlm_fmt.py` | 格式化 |
| `qlm_fuzz.py` | 模糊测试 |
| `qlm_dbinfo.py` | 调试信息统计 |
| `qlm_dbg.py` | 调试器读源码显示 |
| `qlm_cli.py` | `lex` 子命令 |

这些模块大多**不该 import `qlm`** —— `qlm_cli.py` 里甚至有明确注释：
"缓存命中路径不许导入 qlm"（导入编译器要多花几十毫秒，而缓存命中的
意义就是不编译）。让它们为了一个读文件函数去拉进整个编译器是荒谬的。

所以把 `read_source` 抽到这个**零依赖**模块（只用 `os`），谁都能 import。

## 它做什么

1. **解码失败 -> `SyntaxError`**，带文件名与 `行:列`。
   裸的 `UnicodeDecodeError` 有三个问题：没有文件名（多文件构建时不知道
   是哪个）、`position 45` 是**字节偏移**不是行列、不是 `SyntaxError`
   所以 CLI 的错误处理捕不到。

2. **剥掉 UTF-8 BOM**。否则词法器报"非法字符 '\ufeff'"，而用户看不出
   BOM 在哪 —— 这个坑在写测试夹具时踩过不止一次（`Out-File -Encoding utf8`
   会加 BOM）。

3. 给出**可操作建议**（GBK/ANSI 保存、UTF-16）。

## 用法

    from qlm_src import read_source
    text = read_source(path)      # 失败抛 SyntaxError（带文件:行:列）

`qlm.read_source` 保留为转发别名，老调用点不受影响。
"""
import os

__all__ = ["read_source", "read_source_or_none"]


def read_source(path):
    """读源文件，把编码错误翻译成带文件名/行号的 SyntaxError。

    失败抛 `SyntaxError`（**不是** `UnicodeDecodeError`）—— 那是语言层
    预期的失败，CLI 与调用方都按这个类型处理。
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError as e:
        # 用出错字节之前的内容算行列（按字节切，不解码整段）
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            raw = b""
        head = raw[:e.start]
        line = head.count(b"\n") + 1
        col = e.start - (head.rfind(b"\n") + 1) + 1
        bad_byte = raw[e.start] if e.start < len(raw) else 0
        raise SyntaxError(
            f"{os.path.basename(path)}:{line}:{col}: 源文件不是合法的 UTF-8 "
            f"（字节 0x{bad_byte:02x} 无法解码）。"
            f"常见原因：编辑器按 GBK/ANSI 保存，或存成了 UTF-16。"
            f"请转成 UTF-8（无 BOM）。") from None
    # BOM：\ufeff 会让词法器报"非法字符"，而用户看不到它
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def read_source_or_none(path):
    """同 `read_source`，但**任何**失败都返回 None（读不到就当没有）。

    给"读不到也不该崩"的场景用 —— 例如调试器按路径找源码来显示，
    找不到就退化成不显示源码，而不是让整个调试会话失败。
    """
    try:
        return read_source(path)
    except (OSError, SyntaxError):
        return None
