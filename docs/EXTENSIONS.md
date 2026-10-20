# Quelmara 文件扩展名规范

> 状态：v1.0（2026-10-20）。本文件是扩展名的唯一权威来源，`SPEC.md`、CLI 帮助与测试脚本都应与之一致。

## 1. 命名原则

1. **一律小写、三个字母、以 `q` 开头**：`q` 来自 Quelmara，避免与其它语言生态冲突（`.rs` / `.go` / `.py`）。
2. **扩展名即角色**：看后缀就知道这个文件能交给谁、能不能直接运行，不靠目录猜。
3. **一个源文件只有一个扩展名**：不存在 `.qma.txt`、`.qma.in` 之类的中间态。
4. **产物名 = 源文件名基名 + 角色后缀**：`src/hello.qma` → `build/hello.qex`（Windows）或 `build/hello.qel`（Linux/AArch64）。

## 2. 扩展名总表

| 扩展名 | 全称 | 角色 | 产出者 | 消费者 |
|---|---|---|---|---|
| **`.qma`** | Quelmara Module | **源码**（唯一源码扩展） | 人 / 编辑器 / 代码生成器 | `quelmara build`、`quelmara fmt`、`quelmara test` |
| **`.qla`** | Quelmara Library Archive | **库归档**（多个编译单元打成一包） | `quelmara lib`（规划中） | 链接阶段、`quelmara build` |
| **`.qel`** | Quelmara ELF | **可执行**（ELF64） | `build --target native` / `--target arm64` | Linux 内核加载器、`tests/a64_emu.py` |
| **`.qex`** | Quelmara EXecutable | **可执行**（PE32+） | `build --target win` | Windows 加载器、`quelmara run` |
| **`.qir`** | Quelmara IR | **中间表示**（QuIR 文本） | `build --dump-ir` | 人读、优化器调试、跨后端对拍 |
| **`.toml`** | — | **配置** | 人 | 编译器（`Quelmara.toml`） |

### 为什么 `.qel` 和 `.qex` 要分开

可执行格式不同，调试链路也不同：`.qel` 用 `readelf`/`gdb`/自研模拟器，`.qex` 用 PE 工具与 Windows 加载器。同名同后缀会让人分不清手上这份产物该用哪套工具。两者都是"可执行"，但**不是同一种文件**。

Windows 的扩展名不参与加载（`CreateProcess` 只看 PE 头），所以 `.qex` 双击不会自动运行；需要双击时复制一份改名为 `.exe` 即可，`quelmara run` 不受影响。

## 3. 各后端与产物扩展名对照

| `--target` | 输出格式 | 默认扩展名 | 说明 |
|---|---|---|---|
| `native` | 自研 x86_64 裸 ELF64 | `.qel` | 产品默认（Linux） |
| `win` | 自研 PE32+/COFF，无 CRT | `.qex` | 产品默认（Windows） |
| `arm64` | 自研 AArch64 ELF64 | `.qel` | 无 libc |
| `c` | C99 源文件 | `.c` | **仅交叉验证**，不是产品后端 |

`-o` 未指定时，编译器按上表自动补扩展名：

```bash
quelmara build examples/hello.qma --target win      # -> build/hello.qex
quelmara build examples/hello.qma --target native   # -> build/hello.qel
quelmara build examples/hello.qma --target c        # -> build/hello.c
```

`-o` 显式给了扩展名就按给的走（便于把 `.qex` 改名成 `.exe` 交付）。

## 4. 中间产物（不进版本库）

| 文件 | 位置 | 说明 |
|---|---|---|
| `.qir` | `build/*.qir` | 需要 `--dump-ir` 且显式给路径时才落盘；默认只打印到 stdout |
| `*.c` | `build/*.c` | C99 后端中间产物，仅交叉验证用 |
| `*.o` / `.qla` | `build/` | 规划中的目标文件与库归档 |

`build/` 一律 gitignore。

<!-- legacy-ok:begin -->
## 5. 历史扩展名 `.ros`

**已废弃，硬切。** 编译器遇到 `.ros` 会直接报错并给出迁移命令，不做静默兼容：

```
[qlm] 错误：tests/t27_str.ros 使用已废弃的 .ros 扩展名。
      Quelmara 源码扩展名为 .qma，请执行：
      git mv tests/t27_str.ros tests/t27_str.qma
```

理由：两套扩展名长期共存会让"哪些文件还是旧格式"变成永久性的判断负担；项目还没发版，一次切干净成本最低。迁移细节见 `MIGRATION_rosoto_to_quelmara.md`。
<!-- legacy-ok:end -->

## 6. 代码围栏标签

文档里的代码块统一用：

````
```quelmara
fn main() { print("hello") }
```
````

<!-- legacy-ok --> 不再使用 ```` ```rosoto ```` 这种旧围栏标签。

## 7. 与工具链的对应

```
hello.qma ──build--target win────> hello.qex ──run──> Windows 进程
    │                                  ▲
    │                                  └── (复制改名 .exe 可双击)
    ├──build--target native────────> hello.qel ──run──> Linux 进程 / a64 模拟器
    ├──build--target c─────────────> hello.c   ──cc───> 用于交叉验证
    └──build --dump-ir─────────────> hello.qir ────────> 人读 / diff
```
