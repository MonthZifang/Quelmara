# v3.82 — 容器的元素/值类型不能丢（收 §7.28）

- 日期：2026-11-02
- 任务：收 §7.28（v2.43 发现，三个场景，一直靠"夹具里避开这些写法"绕过去）。
- 影响面：`tools/stage0/qlm_native.py`（`_vec_tag_of` / `vec.get` / `map.get`）、
  `tests/selfhost/s46_containerelem.qma`（新增差分夹具）
- 代码改动：约 30 行

## 症状：编得出、跑得完、答案错

```quelmara
let v = vec[f64].new(4)
v.push(1.5)
print(v.get(0))        # stage-0: 4609434218613702656   qlmc: 1.5
print(v.get(0) + 1.0)  # stage-0: 4.609434e+18           qlmc: 2.5
```

`4609434218613702656` 是 1.5 的 IEEE-754 位模式 —— stage-0 把 `vec[f64]` 的
元素当 int 搬，`+ 1.0` 再把这个整数转成 double。`map[K]f64` 一样。

**这比"编不过"更麻烦**：编不过会立刻发现，而这个会把错的输出跑出来，
夹具一旦按它写就会把错的答案钉成"标准答案"。所以 §7.28 的三个场景
**一直没有差分夹具**。

## 真因：`_vec_tag_of` 对 f64 返回 `None`（与 int 无法区分）

`_vec_tag_of` 把元素类型映射成"标签"，下游 `vec.get` / `map.get` 凭标签
决定要不要打浮点/字符串标记：

```python
if et == ("named", "str"):        return "str"
if et ... self.is_agg(et[1]):     return ("agg", name)
if et ... et[1] in NARROW_BITS:   return et[1]
if et and et[0] == "vec":         return ("vecinner", ...)
if et and et[0] == "map":         return ("mapinner", ...)
return None                        # <- f64 掉在这里，和 int 一样
```

`f64` 是标量，落到最后的 `return None`。于是 `vec.get` 里
`if elem == "str"` 不命中、也没有 f64 分支，值就按 int 位模式搬。

## 修法：给 f64 一个标签

### 1. `_vec_tag_of` 返回 `"f64"`

```python
if et == ("named", "f64") or et == ("named", "float"):
    return "f64"
```

用**字符串**标签（与窄标量同构）：消费方全是 `== "str"` / `isinstance(tuple)`
判定，走标量路径不受影响；`push`/`set` 里 `narrow_of(("named", "f64"))`
返回 `None`，不会误截断。

### 2. `vec.get` 补 f64 分支

```python
if elem == "f64":
    self._mark_float(fn, d, "f64")
```

### 3. `map.get` 补 f64 分支

原来只有 `str` 分支：

```python
return self._mark_str(fn, d) if vt == "str" else d
```

改成三分支（str / f64 / 其余）。

## 三个场景的复核

| 场景 | 修前 | 修后 |
|---|---|---|
| (a) 同一函数两张 map，`len()` 读错 | 本机不复现 | ✅ 正确 |
| (a') 同文件多个带 map 的函数 | 本机不复现 | ✅ 正确 |
| (b) `vec[f64]` / `map[K]f64` 元素当 int | ❌ 复现 | ✅ **修好** |
| (c) `len()` 对函数返回的 map | 本机不复现 | ✅ 正确 |

(a) 与 (c) 在当前版本已经正确（可能是 v2.43 之后某轮修掉了），只有 (b)
仍能复现 —— 本版修的就是 (b)。夹具把三个场景都覆盖，防止将来退化。

原始复现件（往 `tests/selfhost/s23_map_grow.qma` 里加回 `count_after_grow()`）
也验证过：stage-0 与 qlmc 输出**逐字节相同**。

## 验证

| 判据 | 结果 |
|---|---|
| `vec[f64]` / `map[K]f64` | ✅ `1.5` / `2.5`（原 `4.6e18`） |
| `s46_containerelem` 与 qlmc 逐字节一致 | ✅ 16 行 IDENTICAL |
| 原始复现件（s23 + count_after_grow） | ✅ 逐字节相同 |
| 全套差分 | ✅ **49/49** |

`s46` 覆盖：`vec[f64]` 元素、`map[K]f64` 值、同函数两张 map、
同文件多 map 函数、函数返回的 map、`vec[str]`（同一条标签通道）。

> 窄标量 `vec[u8]` 也走同一条通道，但 **qlmc 不支持窄类型** —— 那是另一个
> 缺口，不在本条范围内，所以没放进这个差分夹具。
