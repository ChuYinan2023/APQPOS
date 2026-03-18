# NODE-04: BOM — Bill of Materials（物料清单）

**Purpose**: Transform n03 component tree into a structured multi-level BOM with make/buy decisions, supplier hints, and material references.
**Input**: `artifacts/n03-output.json` (components + assembly_interfaces), `artifacts/n01-output.json` (source_index for CTS PPTX BOM page reference)
**Output**: `artifacts/n04-output.json`
**Type**: mixed (AI generates BOM structure; make/buy decisions may need engineer confirmation)

---

## Precondition Check

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger
from reporter import NodeReport

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# n04 depends on n03 (normal edge per network.json)
upstream_ids = ['n03']
error_gaps_total = 0
for uid in upstream_ids:
    a = store.read(uid)
    assert a and a['status'] in ('ready', 'done'), \
        f"上游 {uid} 未完成 (status={a['status'] if a else 'missing'})"
    error_gaps = [g for g in a.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} 有 {len(error_gaps)} 个 error gap")

if error_gaps_total:
    print(f"⚠ 上游共 {error_gaps_total} 个 error gap，本节点结果可能不可靠")

# Verify n03 components list is non-empty
n03 = store.read('n03')
n03_components = n03['payload'].get('components', [])
assert n03_components, "n03 components list is empty — cannot build BOM"
print(f"✓ n03 has {len(n03_components)} component(s)")

# Optionally read n01 for source_index (CTS PPTX BOM page reference)
n01 = store.read('n01')
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 未完成 (status={n01['status'] if n01 else 'missing'})"

# Start logger
log = NodeLogger('<project_path>', 'n04')
log.step("Precondition: upstream artifacts verified")
log.info(f"n03 status: {n03['status']}, confidence_floor: {n03['confidence_floor']}")
log.info(f"n03 components: {len(n03_components)}")
log.info(f"n03 gaps: {[g['rule'] for g in n03.get('gaps', [])]}")
log.info(f"n01 status: {n01['status']}")
```

---

## Execution Steps (Build Mode)

### Step 1: 读取输入字段

```python
log.step("Step 1: Read input fields from n03 and n01")

n03_payload = n03['payload']
n01_payload = n01['payload']

# ── From n03 ──────────────────────────────────────────────────────────────────
components          = n03_payload.get('components', [])
assembly_interfaces = n03_payload.get('assembly_interfaces', [])

# ── From n01: source_index for BOM page reference (optional) ─────────────────
source_index = n01_payload.get('source_index', {})
# Look for CTS PPTX BOM page reference — structure varies by project
bom_page_ref = None
for key, val in source_index.items():
    if isinstance(val, dict):
        pages = val.get('pages', {})
        for page_key, page_val in pages.items():
            if 'bom' in str(page_key).lower() or 'bom' in str(page_val).lower():
                bom_page_ref = {"file": key, "page": page_key, "info": page_val}
                break

log.info(f"n03 components       : {len(components)}")
log.info(f"assembly_interfaces  : {len(assembly_interfaces)}")
log.info(f"bom_page_ref         : {bom_page_ref}")
```

---

### Step 2: 构建 BOM 结构

#### 2a. Make/Buy 决策规则（三层决策）

> **核心原则：AI 只在有充分依据时做决定，否则必须标记 `needs_review=true` 让工程师确认。**

Make/buy 按以下优先级判断，**从上到下，先命中的规则生效**：

```
优先级 1（自动 buy）：组件有客户指定供应商
   → comp.supplier_hint 非空，或 comp.material_hint 中包含供应商名
   → make_or_buy = "buy"，confidence = S1
   → 不需要审阅

优先级 2（自动 buy）：组件是标准件/有认证型号
   → comp.type in (seal, o_ring, clip, fastener, standard_part, sensor,
                    valve, grommet, connector, terminal)
   → make_or_buy = "buy"，confidence = S2
   → 不需要审阅

优先级 3（自动 make）：组件明确属于供应商核心制造工艺
   → comp.type in (tube, wire, harness, end_form)
   → 且 comp.supplier_hint 为空（没有客户指定外购）
   → make_or_buy = "make"，confidence = S2
   → 不需要审阅

优先级 4（需要审阅）：以上规则均不满足
   → make_or_buy = "review_required"
   → needs_review = true
   → 记录到 review_items 列表
   → 生成 R-04-02 gap
```

> **⚠️ 绝对不允许猜测。** 以下情况必须标记 `review_required`：
> - 组件 type 为 damper / bracket / housing / custom / protection 或任何不在规则 2、3 中的类型
> - 组件同时有 make 和 buy 的合理性（如金属管可自制也可外购半成品）
> - 组件的 material_hint 中出现多个备选方案（如 "PA12 or rubber"）
>
> 工程师确认后通过 Optimize 模式更新 make_or_buy 字段。

```python
# PSEUDOCODE — 三层 Make/Buy 决策
#
# AUTO_BUY_TYPES  = {'seal', 'o_ring', 'clip', 'fastener', 'standard_part',
#                    'sensor', 'valve', 'grommet', 'connector', 'terminal'}
# AUTO_MAKE_TYPES = {'tube', 'wire', 'harness', 'end_form'}
#
# def decide_make_buy(comp):
#     # 优先级 1：客户指定供应商 → buy
#     if comp.get('supplier_hint') or has_supplier_name(comp.get('material_hint', '')):
#         return "buy", "S1", False, "客户指定供应商"
#
#     # 优先级 2：标准件类型 → buy
#     if comp['type'] in AUTO_BUY_TYPES:
#         return "buy", "S2", False, f"标准件类型 ({comp['type']})"
#
#     # 优先级 3：核心工艺类型 → make
#     if comp['type'] in AUTO_MAKE_TYPES:
#         return "make", "S2", False, f"核心制造工艺 ({comp['type']})"
#
#     # 优先级 4：无法自动判断 → review_required
#     return "review_required", "S5", True, f"类型 {comp['type']} 不在自动规则中，需工程师确认"
#
# review_items = []
# for comp in n03_components:
#     mob, conf, needs_review, reason = decide_make_buy(comp)
#     if needs_review:
#         review_items.append({
#             "component_ref": comp['id'],
#             "component_name": comp['name'],
#             "component_type": comp['type'],
#             "reason": reason,
#             "material_hint": comp.get('material_hint', ''),
#             "supplier_hint": comp.get('supplier_hint', ''),
#         })
#         log.decision(f"make/buy {comp['id']}", reason, "标记 review_required，等工程师确认", "S5")
```

**当存在 review_required 项时，n04 在写完 artifact 后必须 HALT：**

```
⏸ HALT — n04 有 N 个组件的 make/buy 决策需要工程师确认：

| 组件 | 类型 | 材料提示 | 供应商提示 | 原因 |
|------|------|---------|-----------|------|
| COMP-05 | damper | Nobel Auto... | — | 类型不在自动规则中 |
| ... | ... | ... | ... | ... |

请为每个组件指定 make 或 buy，然后说"继续"。
未确认的项将保持 review_required 状态，下游节点会继承此不确定性。
```

#### 2b. 构建 BOM 行

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — Build BOM rows
#
# BOM 层级定义：
#   L0 = 总成（assembly）— 整个产品
#   L1 = 组件（components from n03）
#   L2 = 子零件（sub-parts, if applicable — e.g., sub-components within an assembly)
#
# 步骤：
#   1. 从 n01 获取项目/产品名称作为 L0 行描述。
#      项目名通常来自 n01_payload 中的 project_name / part_name / description。
#
#   2. 创建 L0 行（总成）：
#      {
#        "level": 0,
#        "item_number": "1000",
#        "description": "<product assembly name>",
#        "quantity": 1,
#        "unit": "ea",
#        "make_or_buy": "assembly",
#        "material_ref": null,
#        "supplier_hint": null,
#        "weight_g": null,
#        "component_ref": null,
#        "confidence": "S1"
#      }
#
#   3. 遍历 n03 components，为每个创建一个 L1 行：
#      item_counter = 1100（递增 100，如 1100, 1200, 1300 ...）
#      {
#        "level": 1,
#        "item_number": str(item_counter),
#        "description": comp['name'],
#        "quantity": comp.get('quantity', 1),
#        "unit": "ea",
#        "make_or_buy": make_or_buy_rules.get(comp['type'], "make"),
#        "material_ref": comp.get('material_hint', comp.get('material', null)),
#        "supplier_hint": comp.get('supplier_hint', null),
#        "weight_g": comp.get('weight_g', null),
#        "component_ref": comp['id'],
#        "confidence": <lowest confidence from comp's dimensions, or "S3" if no dimensions>
#      }
#
#   4. 若 component 包含子组件（sub_components 字段），为每个子组件创建 L2 行：
#      sub_counter = item_counter + 10（递增 10，如 1110, 1120, 1130 ...）
#      同 L1 结构，但 level=2, item_number=str(sub_counter)。
#
#   5. bom = [L0_row] + L1_rows + L2_rows（按 item_number 排序）
```

---

### Step 3: 识别 Gap 和 Assumptions

```python
log.step("Step 3: Gap identification and assumptions")

gaps = []
assumptions = []

# ── R-04-01: n03 组件缺失 ────────────────────────────────────────────────────
# 如果 n03 components 为空，这是 error（但 precondition 已拦截）
# 如果某些 n03 组件的 missing_dimensions 非空，标记 warning
comps_with_missing = [c['id'] for c in components if c.get('missing_dimensions')]
if comps_with_missing:
    msg = (f"{len(comps_with_missing)} component(s) from n03 have missing dimensions, "
           f"BOM weight/material may be incomplete: {comps_with_missing}")
    log.gap("R-04-01", msg, "warning")
    gaps.append({"rule": "R-04-01", "msg": msg, "severity": "warning",
                 "assumption": "BOM rows created with available data; missing fields marked null"})

# ── R-04-02: make/buy 未解析项 ───────────────────────────────────────────────
# 检查是否有 BOM 行的 make_or_buy 基于默认规则（type 不在已知列表中）
unresolved_items = []
for row in bom:
    if row['level'] >= 1 and row.get('_make_buy_defaulted'):
        unresolved_items.append(row['item_number'])
if unresolved_items:
    msg = (f"{len(unresolved_items)} BOM item(s) have make/buy defaulted to 'make' "
           f"— needs engineer review: items {unresolved_items}")
    log.gap("R-04-02", msg, "warning")
    gaps.append({"rule": "R-04-02", "msg": msg, "severity": "warning",
                 "assumption": "Defaulted to 'make' for unknown component types"})

# ── Additional gap: weight not available ─────────────────────────────────────
no_weight = [row['item_number'] for row in bom if row['level'] >= 1 and row.get('weight_g') is None]
if no_weight:
    msg = f"{len(no_weight)} BOM item(s) have no weight estimate: items {no_weight}"
    log.gap("R-04-03", msg, "info")
    gaps.append({"rule": "R-04-03", "msg": msg, "severity": "info",
                 "assumption": "Weight will be populated when 3D model or supplier data is available"})

# ── Assumptions ──────────────────────────────────────────────────────────────
# AI should record all assumptions made during BOM construction:
# - material_ref sourced from n03 component.material_hint (may be approximate)
# - make/buy decisions based on component type heuristic
# - weight estimates are null unless n03 provided them
# Example:
# assumptions.append({
#     "id": "A-01", "field": "make_or_buy",
#     "value": "buy", "unit": null,
#     "confidence": "S3",
#     "rationale": "Standard part type defaults to buy per APQP heuristic"
# })
```

---

### Step 4: 写 Artifact

```python
log.step("Step 4: Build and write artifact")

# ── Confidence floor ──────────────────────────────────────────────────────────
all_confidences = [row.get('confidence', 'S1') for row in bom if row['level'] >= 1]
valid_confs = [c for c in all_confidences if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S3'

# ── Summary counts ────────────────────────────────────────────────────────────
make_count = sum(1 for row in bom if row.get('make_or_buy') == 'make')
buy_count  = sum(1 for row in bom if row.get('make_or_buy') == 'buy')

# ── Clean internal flags from BOM rows before writing ─────────────────────────
for row in bom:
    row.pop('_make_buy_defaulted', None)

# ── Build artifact ────────────────────────────────────────────────────────────
artifact = {
    "node":             "n04",
    "project":          n03.get("project"),
    "status":           "ready",
    "produced_at":      datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":             gaps,
    "assumptions":      assumptions,
    "payload": {
        "bom_version":  1,
        "total_items":  len(bom),
        "make_count":   make_count,
        "buy_count":    buy_count,
        "bom":          bom
    }
}

store.write('n04', artifact)
```

### Step 5: 关闭日志

```python
log.done(artifact)
```

### Step 6: 写报告

```python
# AI 根据本次实际执行情况填写，四个小节不可省略
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n03-output.json` | 组件树 + 装配接口 |
| — | `artifacts/n01-output.json` | source_index (BOM page ref) |

### 过程中解决的问题

- (AI 填写实际遇到的问题及解决方式)

### 假设与判断

- (AI 填写 make/buy 决策依据、材料引用来源、权重估算方式等)

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n04')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Optimize Mode

当用户提供了更精确的数据（替换 S4/S5 假设为 S1/S2 实测值）时：

1. 读取现有 `artifacts/n04-output.json`
2. 初始化 logger，所有 step 标题加 `[Optimize]` 前缀
3. 识别哪些字段被更新（对比新数据 vs 现有 assumptions）
4. 仅更新受影响的 BOM 行，保留未变化的部分
5. 典型 Optimize 场景：
   - 工程师确认 make/buy 决策 → 更新 make_or_buy，移除 R-04-02 gap
   - 供应商提供精确重量 → 更新 weight_g，confidence 升级
   - 材料选型完成（n05 反馈）→ 更新 material_ref
6. 重新计算 `confidence_floor`、`make_count`、`buy_count`
7. 从 `gaps` 和 `assumptions` 中移除已解决的条目
8. 写回 artifact → 关闭日志 → 写报告（同 Build 的 Step 4/5/6）
9. 运行 Validation

### 何时退回 Build 模式

以下情况说明变更超出了局部更新的范围，必须全量重跑：

- n03 组件树发生了结构变化（新增或删除了组件）
- BOM 中新增或删除了行项目
- 上游 n03 的 payload 结构发生变化（新增/删除了字段 key）
- `confidence_floor` 从 S1/S2 降级到 S4/S5（数据质量退化）

如果不确定，选择 Build — 全量重跑比漏更新安全。

---

## Review Mode

仅检查现有 artifact 质量，不修改任何文件：

1. 读取 `artifacts/n04-output.json`
2. 运行下方 Validation 检查
3. 统计：gaps 数量（按 severity）、assumptions 数量、confidence_floor
4. 统计：make_count、buy_count、total_items
5. 检查 BOM 行数是否与 n03 组件数一致
6. 输出质量摘要，不写 artifact

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n04')
p = a.get('payload', {})

# 1. 必填字段检查
assert a.get('status') in ('ready', 'done', 'waiting_human'), "status 无效"
assert a.get('confidence_floor'), "confidence_floor 未设置"

# 2. payload 顶层字段
assert 'bom_version' in p, "payload missing 'bom_version'"
assert 'total_items' in p, "payload missing 'total_items'"
assert 'make_count'  in p, "payload missing 'make_count'"
assert 'buy_count'   in p, "payload missing 'buy_count'"
assert 'bom'         in p, "payload missing 'bom'"

bom = p['bom']
assert isinstance(bom, list) and len(bom) > 0, "bom is empty"

# 3. L0 行存在
l0_rows = [row for row in bom if row.get('level') == 0]
assert len(l0_rows) == 1, f"Expected exactly 1 L0 (assembly) row, found {len(l0_rows)}"

# 4. L1 行数 >= n03 组件数
n03 = store.read('n03')
n03_comp_count = len(n03['payload'].get('components', []))
l1_rows = [row for row in bom if row.get('level') == 1]
assert len(l1_rows) >= n03_comp_count, \
    f"BOM has {len(l1_rows)} L1 rows but n03 has {n03_comp_count} components — BOM is incomplete"

# 5. 每个 BOM 行必须包含必填字段
required_fields = ['level', 'item_number', 'description', 'quantity', 'unit',
                   'make_or_buy', 'confidence']
for row in bom:
    for field in required_fields:
        assert field in row, \
            f"BOM row {row.get('item_number', '?')} missing required field '{field}'"

# 6. make_or_buy 值有效
valid_mob = {'make', 'buy', 'assembly'}
for row in bom:
    valid_mob = ('assembly', 'make', 'buy', 'review_required')
    assert row['make_or_buy'] in valid_mob, \
        f"BOM row {row['item_number']} has invalid make_or_buy='{row['make_or_buy']}'"

# 7. make_or_buy 已设置（无空值）
for row in bom:
    assert row.get('make_or_buy') is not None, \
        f"BOM row {row['item_number']} has make_or_buy=None"

# 8. total_items 与 bom 长度一致
assert p['total_items'] == len(bom), \
    f"total_items={p['total_items']} but bom has {len(bom)} rows"

# 9. make_count + buy_count + assembly count = total
assembly_count = len([r for r in bom if r['make_or_buy'] == 'assembly'])
assert p['make_count'] + p['buy_count'] + assembly_count == len(bom), \
    f"make({p['make_count']}) + buy({p['buy_count']}) + assembly({assembly_count}) != total({len(bom)})"

# 10. gaps 完整性
for g in a.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap 格式不完整: {g}"

print(f"✓ n04 validation passed — confidence_floor: {a['confidence_floor']}")
print(f"  BOM version    : {p['bom_version']}")
print(f"  Total items    : {p['total_items']}")
print(f"  L0 (assembly)  : {len(l0_rows)}")
print(f"  L1 (components): {len(l1_rows)}")
l2_rows = [row for row in bom if row.get('level') == 2]
print(f"  L2 (sub-parts) : {len(l2_rows)}")
print(f"  Make count     : {p['make_count']}")
print(f"  Buy count      : {p['buy_count']}")
print(f"  Gaps           : {[g['rule'] for g in a.get('gaps', [])]}")
```
