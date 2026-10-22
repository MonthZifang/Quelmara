# src/ 三类资源布局（v1.17）

项目目录的源码组织约定：**库（lib）、引用（ref）、资源（asset）**三种形式，
全部由项目 `Quelmara.toml` 的 `[src]` 段定义来源路径，编译器扫描后
**按名称/前缀直接引用**——不需要逐库声明，import 什么解析什么。

```toml
# Quelmara.toml（[src] 段，缺省值如下）
[src]
lib   = "src/lib"     # 库：每个子文件夹/文件 = 一个可 import 的模块
ref   = "src/ref"     # 引用：跨项目引用锚点（.qpm/deps 优先于它）
asset = "src/asset"   # 资源：read_asset() 的运行期基准路径
```

## 目录布局

```
<project>/
  Quelmara.toml          # [src] 段定义三类路径
  main.qma
  src/
    lib/                 # ── 库 ──
      ws/                # ws 库（目录即库，按名称）
        ws_core.qma      #   import ws.ws_core
      http/              # http 库
        http.qma         #   import http.http
    ref/                 # ── 引用 ──（跨项目锚点；qpm 依赖走 .qpm/deps）
    asset/               # ── 资源 ──
      greeting.txt       #   read_asset("greeting.txt")
      levels/level1.bin  #   read_asset("levels/level1.bin")
```

## 三种形式

| 形式 | 路径 | 引用方式 | 语义 |
|---|---|---|---|
| **库** | `[src].lib` | `import ws.ws_core` | 编译期扁平合并进 AST（代码） |
| **引用** | `[src].ref` + `.qpm/deps` | `import <dep>.<mod>` | 外部代码（qpm install 拉取锁定） |
| **资源** | `[src].asset` | `read_asset("name")` | 运行期读取（数据文件，不参与编译） |

## 引用规则（按前缀、按需，非一次性全量）

- `import ws.ws_core` 只解析 `src/lib/ws/ws_core.qma` 这**一个文件**——
  lib 下其他库/其他文件不加载（惰性解析，import 什么拉什么）。
- 查找顺序：主文件目录 → 仓库根 `std/` → **`[src].lib`** → **`[src].ref`**
  → `.qpm/deps`（qpm 依赖，按**主项目根**解析）。
- 单文件库 `lib/ws.qma` 与目录库 `lib/ws/core.qma` 都支持；
  连字符不能出现在 import 段名（包名用下划线）。

## read_asset(name)

```quelmara
let text = read_asset("greeting.txt")        // src/asset/greeting.txt
let bin  = read_asset("levels/level1.bin")   // 子目录同样支持
```

- asset 根在**编译期嵌入**（绝对路径），运行期与 name 拼接后走 read_text。
- name 支持子目录；路径分隔符用 `/`。
- 读取失败 fail-fast（与 read_text 同策略）。

## 端到端示例

`fixtures/srcproj/`：`src/lib/ws/ws_core.qma`（库）+ `src/asset/greeting.txt`
（资源）+ `main.qma`（import + read_asset）——
`t60_srclayout` 回归覆盖（PE 122 项内）。

## 边界（登记 GAPS）

- `ref` 目前只是查找路径（锚点文件），跨项目引用的版本解析走 qpm。
- 资源**打包进 exe**（嵌入资源段）未做——read_asset 是运行期文件读取。
- lib 库的 `module` 声明只作文档，不参与命名空间（扁平合并语义不变）。
- 源码行号传播（诊断信息带 file:line）仍在 GAPS。
