# P2 方向1 任务清单：`symbol` 可用性

## 实现

- [x] `SYMBOL_DEFINITION_PATTERNS`：扩展名 → 定义正则
  - [x] `.js/.jsx/.ts/.tsx/.mjs/.cjs/.vue/.svelte`：`function`、`class`、`const/let/var name =`、`interface/type/enum`
  - [x] `.go`：`func name(`、`func (recv) name(`、`type name struct`
  - [x] `.java/.kt/.kts/.scala`：`class/interface/enum/record/object name`、方法签名
  - [x] `.rb`：`def name`
  - [x] `.rs`：`fn`、`struct`、`enum`、`trait`、`union`
  - [x] `.php`：`function name`
- [x] `_imported_names(tree)`：`Import`/`ImportFrom` 名字与别名
- [x] Python 通道：AST 定义 + caller + callee，`confidence="exact"`
- [x] 文本通道：正则定义 + `\bname\b` 引用，`confidence="heuristic"`
- [x] `symbol()` 汇总
  - [x] `definitions` 每项带 `confidence`
  - [x] `callers` 每项带 `scope`（`local` / `imported` / `unresolved`）
  - [x] `summary`：`exact_definitions`、`heuristic_definitions`、`unresolved_callers`
  - [x] 保留 `len(definitions) + len(callers) > 300` 提前退出与 `[:100]` 截断
  - [x] 单行取前 500 字符

## 测试

- [x] `tests/test_symbol_lookup.py`（12 用例）
  - [x] Python 定义 `confidence="exact"`
  - [x] JS `function` / `const =` 定义，`confidence="heuristic"`
  - [x] Go 带接收者的方法定义
  - [x] `scope` 三态各一例（local / imported / unresolved）
  - [x] 同名消歧：两处定义 + 一处无来处调用
  - [x] 长名字不误匹配短名字（`formatCompact` vs `format`）
  - [x] Python 文件不被文本通道重复扫描
  - [x] 不支持的扩展名整份跳过
  - [x] 超长行在匹配前被裁剪
  - [x] `summary` 计数一致
- [x] 调整 `tests/test_repository_source.py` 的 definitions 断言

## 验证

- [x] 全量回归：**227 用例，0 失败 0 错误**（本步新增 12）

## 实施中的一处设计修正（已回写 specify.md）

原计划让「无法识别的扩展名参与引用查找」，实施时改为**整份跳过**。
理由：`LocalTree` 形态下面对的是整库，对 `.md`/`.json`/`.lock` 做无差别 `\bname\b`
扫描既慢又全是噪音。现在只处理两种文件：Python（AST）与有定义模板的语言族（正则）。
不支持的语言返回空结果，比返回一堆假 caller 更诚实。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交

