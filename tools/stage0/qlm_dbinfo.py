#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 调试信息（stage-0 工具链模块，v1.62）
============================================
调试器链路的第一段：让编译器把"源码行号 + 变量位置"随 PE 一起发出。

三件事：
1. **行号钩子**：临时给 `qlm.Parser.parse_stmt` 包一层，给每个语句元组
   追加 `("__line__", n)` 尾部元素（既有代码全部索引访问，不受影响）。
   钩子只在加载调试程序期间安装、用完即卸——不改共享 parser 文件
   （语言轨在途重写 `qlm.py`，避免文件面冲突）。
2. **load_program_dbg**：带行号的程序加载 + 主文件函数名集。import 的库
   函数行号属于别的文件，本版不配——调试器对那些帧显示 `<library>`。
3. **serialize_dbg**：Codegen 收集的调试表 + 结构体布局 -> JSON 字节，
   由 `qlm_pe` 写进 PE 的 `.qlmdbg` 节（自研格式，**非** DWARF/PDB；
   不挂 DEBUG_DIRECTORY，避免标准工具按 CODEVIEW 误读）。

数据流：
    qlm_dbinfo.load_program_dbg
      -> lower_and_optimize(prog=...)        # Lower 发射 line/dbgvar 标记
      -> Codegen 收集 {funcs:[{name,file,rva,lines,vars}]}
      -> qlm_dbinfo.serialize_dbg -> .qlmdbg 节
      -> qlm_dbg.py 读节、下断点、读变量
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qlm  # noqa: E402

# ---------------------------------------------------------------------------
# 1. 行号钩子（只包 parse_stmt 一层，安装/卸载成对）
# ---------------------------------------------------------------------------

_orig_parse_stmt = None


def install_stmt_lines():
    """给 Parser.parse_stmt 包上"记录语句行号"的外壳。

    外层先 `peek()` 取行号（不消耗 token），再调原函数；语句元组拿到
    统一的 `("__line__", n)` 尾部元素。嵌套语句经 parse_block 递归，
    全部覆盖。"""
    global _orig_parse_stmt
    if _orig_parse_stmt is not None:
        return
    _orig_parse_stmt = qlm.Parser.parse_stmt

    def parse_stmt(self):
        line = self.peek().line
        node = _orig_parse_stmt(self)
        return node + (("__line__", line),)

    qlm.Parser.parse_stmt = parse_stmt


def uninstall_stmt_lines():
    global _orig_parse_stmt
    if _orig_parse_stmt is not None:
        qlm.Parser.parse_stmt = _orig_parse_stmt
        _orig_parse_stmt = None


# ---------------------------------------------------------------------------
# 2. 带行号的程序加载
# ---------------------------------------------------------------------------

def load_program_dbg(src_path, cfg=None):
    """加载带行号标记的程序。

    返回 lower_and_optimize(prog=...) 所需的字典：
      fns_ast  合并后的 AST（语句带 ("__line__", n)）
      tests / structs / enums  与 load_program 同口径
      main_fns 主文件定义的函数名集合（只有它们配源码行号）
    """
    install_stmt_lines()
    try:
        res = qlm.load_program(src_path, cfg)
        # 主文件独有函数名：再单独解析一份主文件（不解析 import），
        # 取其中定义的函数名。import 进来的库函数不在此列。
        with open(src_path, encoding="utf-8") as f:
            main_res = qlm.Parser(qlm.tokenize(f.read())).parse_program()
        main_fns = {fd["name"] for fd in main_res[2]}
    finally:
        uninstall_stmt_lines()
    _mod, _imports, fns_ast, tests, structs, enums, _order = res
    return {"fns_ast": fns_ast, "tests": tests, "structs": structs,
            "enums": enums, "main_fns": main_fns}


# ---------------------------------------------------------------------------
# 3. 序列化（.qlmdbg 节体）
# ---------------------------------------------------------------------------

def serialize_dbg(dbg, src_path, struct_layout):
    """Codegen 调试表 -> JSON 字节。

    格式（version 1）：
      {"version":1, "src": <编译时传入的源路径>,
       "structs": {名字: {"words": N, "fields": [[字段, 类型, 字偏移]]}},
       "funcs":  [{"name","file","rva","lines":[[off,line]...],
                    "vars":[{"name","kind","s","bind","loc","last"}]}]}
    loc = ["r", 寄存器号] | ["m", 帧槽字节距]（地址 = rbp - off）
    """
    out = {"version": 1,
           "src": src_path.replace("\\", "/"),
           "structs": struct_layout,
           "funcs": dbg["funcs"]}
    return json.dumps(out, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
