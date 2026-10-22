# P2 方向1 SPEC：`symbol` 的可用性（多语言 + 证据强度标注）

## 现状证据

**只对 Python 生效**

- `pragent/repository_tools.py:163`：`if not relative.endswith(".py"): continue`。
  非 Python 文件被整份跳过，`symbol` 对 JS/TS/Go/Java 仓库返回空结果，而不是说「不支持」。

**同名碰撞当成确定命中**

- `pragent/repository_tools.py:170-188`：`ast.walk` 全树扫描，
  `isinstance(node, ast.Call)` 里取 `func.id`（裸名）或 `func.attr`（属性名），
  与目标名 `==` 比较即记为 caller。
- 后果：`obj.helper()` 与 `helper()` 不加区分；`a.py:helper` 与 `b.py:helper` 是两个
  不同函数时同样互相记成调用关系；不解析 import，不看作用域。
- 这在 step2 之后收窄了影响面（冻结集只有被改文件），但没有消失：一个 PR 改两个同名
  工具函数的场景很常见。

**没有任何证据强度标注**

- 返回值只有 `definitions`/`callers`/`callees` 三个列表，模型无法区分
  「AST 确认的定义」与「字符串撞上的同名」。
- `pragent/gates.py:133-136` 的 `STRONG_EVIDENCE_TOOLS` 把 `symbol` 当作强证据，
  但它现在给出的结论并不都是强的。

## 目标（可验收）

1. 非 Python 文件参与定义查找，按语言族使用固定正则；命中的定义带
   `confidence: "heuristic"`，Python 的 AST 定义带 `confidence: "exact"`。
2. Python 的每个 caller 增加 `scope` 字段，取值：
   - `local`：该文件自己定义了这个名字；
   - `imported`：该文件 import 了这个名字；
   - `unresolved`：既没定义也没 import，无法确认是同一个符号。
3. 非 Python 的 caller 一律 `scope: "unresolved"`，因为它们只有文本匹配。
4. 返回值增加 `summary`：`exact_definitions`、`heuristic_definitions`、
   `unresolved_callers` 三个计数。
5. 现有 215 用例全绿；`symbol` 的参数 schema 不变。

## 非目标

- **不做跨文件类型推断**。判断 `obj.helper()` 里 `obj` 的真实类型需要完整类型系统，
  那是 tree-sitter + 类型检查器的工作量。本步只把不确定性显式化，不假装能消除它。
- 不引入任何解析依赖。`requirements.txt` 当前没有 tree-sitter，加它会改变部署形态。
- 不改 `gates.py` 的 `STRONG_EVIDENCE_TOOLS` 名单。降低强度的信息先给到模型，
  是否调整门禁在 step4 用真实 PR 数据决定，不能凭猜。
- 不改变 `callees` 的语义（它描述「定义体内调用了什么」，与同名问题无关）。

## 设计决策

**按扩展名分组选正则，而不是通用正则**

定义形态在不同语言里差异太大：`func (r T) Name(` 与 `const name = (` 无法用一条正则
覆盖。按 `.js/.ts/.go/.java/.rb/.rs/.php` 分组，每组一条锚定行首的定义正则。
**无法识别的扩展名整份跳过**，不做引用扫描 —— 实施时判定「对整库做无差别 `\bname\b`
搜索」既慢又全是噪音，返回空结果比返回一堆假 caller 更诚实。

**`scope` 靠 import 表判定，不靠路径解析**

`_imported_names(tree)` 收集 `Import`/`ImportFrom` 引入的名字（含别名）。
一个文件里出现同名调用且该名字在 import 表里，就标 `imported`；若同时还定义了同名符号，
标 `local` 优先。这样能区分「本文件的函数」与「从别处引入的函数」，但**不尝试确认
是哪一个别处的函数** —— 那需要模块路径解析，超出本步范围。

**强度信息进返回值而不是改门禁**

`symbol` 的输出是给模型看的。把 `confidence`/`scope` 放进输出，模型可以在结论里降级
措辞；而直接改门禁名单会让现有 215 个用例的语义同时变化，且没有真实 PR 数据支撑。
先给信息，再调门禁，顺序不能反。

## 约束

- `symbol` 在 Worker 线程里被并发调用（`agentic_core.py` 的 ThreadPoolExecutor），
  实现必须只读。正则表是模块级常量，编译一次。
- 冻结集通常只有 3-10 个文件，因此全量扫描的代价可以接受；`len(definitions) +
  len(callers) > 300` 的提前退出保留。
- 输出规模上限沿用现有的 `[:100]` 截断，避免把上下文撑爆。
- 单行匹配必须限制行长（取前 500 字符），否则压缩过的 JS 会产生巨大行。
