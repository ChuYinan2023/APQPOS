# NODE-05: Material Selection（材料选型）

**Purpose**: For each "make" item in n04 BOM, select a specific material grade and supplier based on n01 performance requirements and compliance constraints.
**Input**: `artifacts/n04-output.json` (BOM make items), `artifacts/n03-output.json` (component material_hint, dimensions), `artifacts/n01-output.json` (material_compliance, performance_requirements, referenced_standards)
**Output**: `artifacts/n05-output.json`
**Type**: mixed (AI recommends materials, engineer confirms)

---

## Precondition Check

```python
import json, sys
from pathlib import Path

_APQPOS = next(p for p in [Path.cwd()] + list(Path.cwd().parents)
               if (p / '.claude/skills/apqp-os/scripts').exists())
sys.path.insert(0, str(_APQPOS / '.claude/skills/apqp-os/scripts'))
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# n05 depends on n03 (normal) and n04 (secondary) per network.json
# n01 is accessed transitively for requirements data
upstream_ids = ['n03', 'n04']
error_gaps_total = 0
for uid in upstream_ids:
    a = store.read(uid)
    assert a and a['status'] in ('ready', 'done'), \
        f"上游 {uid} 未完成 (status={a['status'] if a else 'missing'})"
    error_gaps = [g for g in a.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} 有 {len(error_gaps)} 个 error gap")

# Also verify n01 is available (transitive dependency)
n01 = store.read('n01')
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 未完成 (status={n01['status'] if n01 else 'missing'}) — material_compliance/performance_requirements unavailable"

if error_gaps_total:
    print(f"⚠ 上游共 {error_gaps_total} 个 error gap，本节点结果可能不可靠")

# 初始化 logger
log = NodeLogger('<project_path>', 'n05')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids + ['n01']:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: 读取输入 — 收集 make 项和约束

```python
log.step("Step 1: Read upstream artifacts — BOM make items, component hints, requirements")
```

1. **Read n04 BOM** (`artifacts/n04-output.json`):
   - Extract `payload.bom_items` (or equivalent list field)
   - Filter to items where `make_or_buy == "make"` — only these need material selection
   - Record each item's `item_number`, `component_ref`, `part_name`, `quantity`

2. **Read n03 components** (`artifacts/n03-output.json`):
   - For each make item, find its matching component in `payload.components` by `component_ref`
   - Extract `material_hint` (e.g. "PA12", "NBR rubber", "stainless steel") — this is the starting point for selection
   - Extract relevant `dimensions` (wall thickness, OD, ID, length) — needed for density-based weight calculation later

3. **Read n01 requirements** (`artifacts/n01-output.json`):
   - `payload.performance_requirements` — temperature range, chemical resistance, pressure, mechanical loads
   - `payload.material_compliance` — restricted substances (ELV, REACH), IMDS requirement, OEM-specific bans
   - `payload.referenced_standards` — OEM material specs (e.g. MS.50017, VW TL, BMW GS) that constrain material choice
   - `payload.special_characteristics` — any SC/CC tied to material properties (e.g. chemical resistance rating)

```python
n04 = store.read('n04')
n03 = store.read('n03')
n01 = store.read('n01')

bom_items = n04['payload'].get('bom_items', [])
make_items = [item for item in bom_items if item.get('make_or_buy') == 'make']
log.info(f"BOM total: {len(bom_items)}, make items requiring material selection: {len(make_items)}")

components = {c['component_ref']: c for c in n03['payload'].get('components', [])}
perf_reqs = n01['payload'].get('performance_requirements', [])
compliance = n01['payload'].get('material_compliance', {})
ref_standards = n01['payload'].get('referenced_standards', [])

log.info(f"Performance requirements: {len(perf_reqs)}")
log.info(f"Restricted substances: {compliance.get('restricted', [])}")
log.info(f"Referenced standards: {len(ref_standards)}")
```

---

### Step 2: 材料选型决策树 — 逐项推理

```python
log.step("Step 2: Material selection decision tree — evaluate each make item")
```

For each make item, apply the following decision tree:

#### 2a. Determine component type category

Classify the component into one of these functional categories (extend as needed):

| Category | Examples | Typical material families |
|----------|----------|--------------------------|
| Tube / pipe | fuel line, coolant hose, brake line | PA12, PA612, PA6, POM, PVDF, stainless steel |
| Housing / body | valve body, filter housing, connector body | PA66-GF, PPA-GF, POM, aluminum die-cast |
| Seal / O-ring | static seal, dynamic seal, gasket | FKM, NBR, EPDM, HNBR, silicone |
| Bracket / clip | mounting bracket, retaining clip | PA66-GF, POM, spring steel, stainless steel |
| Spring / pin | return spring, retention pin | spring steel, stainless steel |
| Insert / bushing | metal insert, press-fit bushing | brass, stainless steel, carbon steel |
| Connector / coupling | quick-connect, barb fitting | PA66-GF, POM, PPA-GF, acetal |
| Cover / cap | protective cap, dust cover | PP, PE, TPE |
| Label / marking | identification label, laser marking substrate | (not material-selected — skip or mark N/A) |

#### 2b. Apply performance requirement filters

For each component, identify which n01 performance requirements apply based on:
- **Temperature range**: what is the operating and peak temperature? Eliminates materials with insufficient Tg/Tm
- **Chemical exposure**: fuel types (gasoline, diesel, bio-blend), coolant, brake fluid, salt spray — eliminates non-resistant materials
- **Pressure**: burst pressure, working pressure — sets minimum wall thickness or eliminates weak materials
- **Mechanical loads**: vibration, pull-apart force, impact — sets minimum tensile/impact strength
- **UV / weathering**: exterior-exposed components need UV stabilization
- **Electrical**: static dissipation requirements (fuel system) — may require conductive or dissipative grades

```
For each make item:
  1. Read material_hint from n03 component
  2. Identify applicable performance requirements from n01
  3. Build candidate list: start from material_hint, add known alternatives for this component category
  4. Eliminate candidates that fail any hard requirement (temperature, chemical, compliance)
  5. Rank remaining candidates by: cost, processability, OEM approval status, supply chain risk
  6. Select top candidate; record alternatives
```

#### 2c. Apply compliance filters

For each candidate material, verify:
- **ELV compliance** (EU Directive 2000/53/EC): no Pb, Hg, Cd, Cr6+ above thresholds
- **REACH compliance**: check against SVHC candidate list
- **OEM-specific restrictions**: from n01 `material_compliance.standards` and `referenced_standards`
- **OEM material approval**: if n01 references a specific OEM material spec (e.g. MS.50017, VW TL 52435), the selected grade must appear on that spec's approved list, or be flagged as `needs_review`

```python
selections = []
unresolved_count = 0

for item in make_items:
    comp_ref = item.get('component_ref')
    comp = components.get(comp_ref, {})
    material_hint = comp.get('material_hint', '')
    dims = comp.get('dimensions', {})

    # AI reasoning: apply decision tree
    # ... (component category, performance filters, compliance check)

    selection = {
        "component_ref": comp_ref,
        "bom_item_number": item.get('item_number', ''),
        "material_name": "",       # e.g. "PA12", "FKM", "SS304"
        "grade": "",               # e.g. "Rilsan BESNO TL", "Viton A-401C"
        "supplier": "",            # e.g. "Arkema", "DuPont"
        "density_g_cm3": 0.0,
        "unit_price_eur_kg": 0.0,  # estimate — confidence S3 or S4
        "elv_compliant": True,     # True / False / None (unknown)
        "reach_compliant": True,
        "oem_spec_ref": "",        # OEM material spec number if applicable
        "selection_rationale": "",  # concise explanation of why this material was chosen
        "alternatives": [],        # list of alternative material names considered
        "needs_review": False,     # True if selection is uncertain
        "confidence": "S3"         # S3 = industry-standard choice; S4 = assumption
    }

    # If multiple candidates are equally viable or material_hint is vague:
    if uncertain:
        selection["needs_review"] = True
        selection["confidence"] = "S4"
        unresolved_count += 1
        log.warn(f"{comp_ref}: material selection uncertain — {len(candidates)} viable candidates, flagged for review")

    selections.append(selection)
    log.info(f"{comp_ref} ({item.get('part_name','')}): {selection['material_name']} / {selection['grade']} — {selection['selection_rationale'][:60]}")
```

---

### Step 3: 置信度与假设管理

```python
log.step("Step 3: Confidence assessment and assumption tracking")
```

**Confidence rules for material selection:**

| Data source | Confidence |
|-------------|------------|
| OEM-approved material list with specific grade | S1 |
| Material specified in customer drawing / CTS | S2 |
| Industry-standard material for component type (e.g. PA12 for fuel lines per SAE J2044) | S3 |
| AI assumption based on material_hint + generic requirements | S4 |
| No material_hint, no clear requirements — pure guess | S5 |

For each selection, record assumptions where actual data is missing:

```python
assumptions = []
for sel in selections:
    if sel['confidence'] in ('S4', 'S5'):
        assumptions.append({
            "id": f"A-05-{sel['component_ref']}",
            "field": f"material for {sel['component_ref']}",
            "value": f"{sel['material_name']} / {sel['grade']}",
            "unit": "",
            "confidence": sel['confidence'],
            "rationale": sel['selection_rationale']
        })
    # Unit price is almost always an estimate
    assumptions.append({
        "id": f"A-05-{sel['component_ref']}-price",
        "field": f"unit_price_eur_kg for {sel['component_ref']}",
        "value": str(sel['unit_price_eur_kg']),
        "unit": "EUR/kg",
        "confidence": "S4" if sel['unit_price_eur_kg'] > 0 else "S5",
        "rationale": "Market estimate; confirm with supplier quotation"
    })
```

---

### Step 4: Gap 检查

```python
log.step("Step 4: Gap identification")
```

| Gap | Rule | Severity | Condition |
|-----|------|----------|-----------|
| Make item has no material selection | R-05-01 | error | A make item in n04 BOM has no corresponding entry in `selections` |
| Material selection needs engineer review | R-05-02 | warning | `needs_review == true` — multiple viable candidates, no clear winner |

```python
gaps = []

# R-05-01: every make item must have a selection
selected_refs = {s['component_ref'] for s in selections}
for item in make_items:
    ref = item.get('component_ref')
    if ref not in selected_refs:
        gaps.append({
            "rule": "R-05-01",
            "msg": f"Make item {ref} ({item.get('part_name','')}) has no material selection",
            "severity": "error"
        })

# R-05-02: selections flagged for review
for sel in selections:
    if sel.get('needs_review'):
        gaps.append({
            "rule": "R-05-02",
            "msg": f"{sel['component_ref']}: material selection uncertain — {sel['material_name']}/{sel['grade']} needs engineer review",
            "severity": "warning",
            "assumption": sel['selection_rationale']
        })

log.info(f"Gaps: {len([g for g in gaps if g['severity']=='error'])} error, {len([g for g in gaps if g['severity']=='warning'])} warning")
```

---

### Step 5: 写 artifact

```python
log.step("Step 5: Write artifact")

# Determine confidence_floor: lowest confidence across all selections
conf_order = ['S1', 'S2', 'S3', 'S4', 'S5']
all_confs = [s['confidence'] for s in selections]
confidence_floor = max(all_confs, key=lambda c: conf_order.index(c)) if all_confs else 'S5'

artifact = {
    "node": "n05",
    "project": "<project_id>",
    "status": "ready",
    "produced_at": "<ISO8601>",
    "confidence_floor": confidence_floor,
    "gaps": gaps,
    "assumptions": assumptions,
    "payload": {
        "selections": selections,
        "unresolved_count": unresolved_count
    }
}
store.write('n05', artifact)
```

---

### Step 6: 关闭日志

```python
log.done(artifact)
```

---

### Step 7: 写报告

```python
from reporter import NodeReport

# AI 根据本次实际执行情况填写，四个小节不可省略
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n04-output.json` | BOM — make items filtered for material selection |
| — | `artifacts/n03-output.json` | Component tree — material_hint, dimensions |
| — | `artifacts/n01-output.json` | Performance requirements, material compliance, referenced standards |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n05')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n05",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S3",
  "gaps": [
    {
      "rule": "R-05-02",
      "msg": "COMP-03: material selection uncertain — NBR/Perbunan 3945 needs engineer review",
      "severity": "warning",
      "assumption": "NBR chosen over FKM based on cost; FKM may be required if chemical exposure exceeds NBR limits"
    }
  ],
  "assumptions": [
    {
      "id": "A-05-COMP-01",
      "field": "material for COMP-01",
      "value": "PA12 / Rilsan BESNO TL",
      "unit": "",
      "confidence": "S3",
      "rationale": "Industry-standard PA12 grade for automotive fuel lines per SAE J2044"
    }
  ],
  "payload": {
    "selections": [
      {
        "component_ref": "COMP-01",
        "bom_item_number": "1.1",
        "material_name": "PA12",
        "grade": "Rilsan BESNO TL",
        "supplier": "Arkema",
        "density_g_cm3": 1.02,
        "unit_price_eur_kg": 8.5,
        "elv_compliant": true,
        "reach_compliant": true,
        "oem_spec_ref": "MS.50017",
        "selection_rationale": "PA12 is the industry-standard material for automotive fuel supply lines; Rilsan BESNO TL is OEM-approved for fuel contact per MS.50017",
        "alternatives": ["PA612", "PA6"],
        "needs_review": false,
        "confidence": "S3"
      }
    ],
    "unresolved_count": 0
  }
}
```

---

## Optimize Mode

当用户提供了更精确的数据（替换 S4/S5 假设为 S1/S2 实测值）时：

1. 读取现有 `artifacts/n05-output.json`
2. 初始化 logger，所有 step 标题加 `[Optimize]` 前缀
3. 识别哪些 selections 被更新（对比新数据 vs 现有 assumptions）
4. 典型 Optimize 触发场景：
   - 工程师确认材料选择（`needs_review` → false, confidence 升级）
   - 供应商报价到位（unit_price_eur_kg 从 S4 估计 → S1 实际报价）
   - OEM 批准特定牌号（oem_spec_ref 从空 → 填入具体规范号）
   - 上游 n04 BOM 更新了 make/buy 分类（新增或减少 make 项）
5. 仅更新受影响的 selections，保留未变化的部分
6. 重新计算 `confidence_floor`
7. 从 `gaps` 和 `assumptions` 中移除已解决的条目
8. 写回 artifact → 关闭日志 → 写报告
9. 运行 Validation

### 何时退回 Build 模式

以下情况必须全量重跑：

- n04 BOM 中 make 项**新增或删除**（selections 列表结构变化）
- n01 performance_requirements **新增了关键约束**（如新增化学暴露条件，可能淘汰已选材料）
- n03 component 的 material_hint **从具体材料改为完全不同的材料族**
- `confidence_floor` 从 S1/S2 **降级**到 S4/S5

如果不确定，选择 Build — 全量重跑比漏更新安全。

---

## Review Mode

仅检查现有 artifact 质量，不修改任何文件：

1. 读取 `artifacts/n05-output.json`
2. 运行下方 Validation 检查
3. 统计：gaps 数量（按 severity）、assumptions 数量、confidence_floor、needs_review 数量
4. 输出质量摘要，不写 artifact

---

## Validation

```python
# 在 Build/Optimize 完成后运行
import json, sys
from pathlib import Path

_APQPOS = next(p for p in [Path.cwd()] + list(Path.cwd().parents)
               if (p / '.claude/skills/apqp-os/scripts').exists())
sys.path.insert(0, str(_APQPOS / '.claude/skills/apqp-os/scripts'))
from store import ArtifactStore

store = ArtifactStore('<project_path>')
artifact = store.read('n05')
p = artifact.get('payload', {})

# 1. 必填字段检查
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status 无效"
assert artifact.get('confidence_floor'), "confidence_floor 未设置"

# 2. selections 非空
selections = p.get('selections', [])
assert len(selections) > 0, "selections 为空 — 至少需要一个 make 项的材料选型"

# 3. 每个 selection 必填字段完整
for sel in selections:
    assert sel.get('component_ref'), f"selection 缺少 component_ref: {sel}"
    assert sel.get('material_name'), f"{sel['component_ref']}: material_name 为空"
    assert sel.get('grade'), f"{sel['component_ref']}: grade 为空"
    assert sel.get('supplier'), f"{sel['component_ref']}: supplier 为空"
    assert sel.get('density_g_cm3') and sel['density_g_cm3'] > 0, \
        f"{sel['component_ref']}: density_g_cm3 无效"
    assert sel.get('selection_rationale'), \
        f"{sel['component_ref']}: selection_rationale 为空"
    assert sel.get('confidence') in ('S1', 'S2', 'S3', 'S4', 'S5'), \
        f"{sel['component_ref']}: confidence 无效: {sel.get('confidence')}"
    # ELV/REACH must be explicitly set (True/False), not None
    assert sel.get('elv_compliant') is not None, \
        f"{sel['component_ref']}: elv_compliant 未设置"
    assert sel.get('reach_compliant') is not None, \
        f"{sel['component_ref']}: reach_compliant 未设置"

# 4. Cross-check: every n04 make item has a selection
n04 = store.read('n04')
if n04:
    bom_items = n04['payload'].get('bom_items', [])
    make_refs = {item['component_ref'] for item in bom_items if item.get('make_or_buy') == 'make'}
    selected_refs = {s['component_ref'] for s in selections}
    missing = make_refs - selected_refs
    assert not missing, \
        f"R-05-01 violation: make items without material selection: {missing}"

# 5. unresolved_count consistency
needs_review_count = sum(1 for s in selections if s.get('needs_review'))
assert p.get('unresolved_count', 0) == needs_review_count, \
    f"unresolved_count ({p.get('unresolved_count')}) != actual needs_review count ({needs_review_count})"

# 6. gaps 完整性
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap 格式不完整: {g}"

# 7. R-05-02 gaps match needs_review selections
review_gaps = {g['msg'].split(':')[0] for g in artifact.get('gaps', []) if g['rule'] == 'R-05-02'}
review_sels = {s['component_ref'] for s in selections if s.get('needs_review')}
# Every needs_review selection should have a corresponding R-05-02 gap
for ref in review_sels:
    assert any(ref in g['msg'] for g in artifact.get('gaps', []) if g['rule'] == 'R-05-02'), \
        f"{ref} has needs_review=true but no R-05-02 gap"

print(f"✓ n05 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Selections: {len(selections)}")
print(f"  Needs review: {needs_review_count}")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
print(f"  Assumptions: {len(artifact.get('assumptions', []))}")
```
