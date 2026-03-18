# NODE-03: 3D 数模解析（3D Model Parser）

**Purpose**: 从 n01 geometry 和 n02 CAT-04 聚合组件树和装配接口，供 n04–n08 消费。
无 3D 模型时以 fallback 模式运行；3D 模型到来时增量更新（geometry_version + 1）。
**Input**: `artifacts/n01-output.json`, `artifacts/n02-output.json`
**Output**: `artifacts/n03-output.json`
**Type**: auto-fallback（无 3D 模型时全自动；有 3D 模型时需人工触发增量更新）

---

## Precondition Check

```python
import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger
from reporter import NodeReport

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

n01 = store.read('n01')
n02 = store.read('n02')

assert n01['status'] == 'ready', \
    f"n01 status is '{n01['status']}' — must be 'ready' before running n03"
assert n02['status'] == 'ready', \
    f"n02 status is '{n02['status']}' — must be 'ready' before running n03"
assert n01['payload'].get('geometry'), \
    "n01 payload.geometry is empty — n03 cannot build component tree (R-03-01 error)"

# Start logger — do this ONCE after precondition passes
log = NodeLogger('<project_path>', 'n03')
log.step("Precondition: n01 and n02 ready, geometry present")
log.info(f"n01 confidence_floor: {n01['confidence_floor']}")
log.info(f"n02 confidence_floor: {n02['confidence_floor']}")
log.info(f"n01 gaps: {[g['rule'] for g in n01.get('gaps', [])]}")
log.info(f"n02 gaps: {[g['rule'] for g in n02.get('gaps', [])]}")
```

---

## Execution Steps

### Step 1: 读取输入字段

```python
log.step("Step 1: Read input fields from n01 and n02")

n01_payload = n01['payload']
n02_payload = n02['payload']

# ── From n01 ──────────────────────────────────────────────────────────────────
geometry        = n01_payload.get('geometry', {})
sc_cc           = n01_payload.get('special_characteristics', [])
material        = n01_payload.get('material_compliance', {})
qc              = n01_payload.get('quick_connector', {})

# Detect 3D model availability (n01 R-01-04 gap indicates no 3D model)
n01_gap_rules = [g['rule'] for g in n01.get('gaps', [])]
has_3d_model  = 'R-01-04' not in n01_gap_rules
geometry_version = 1  # incremented when 3D model arrives later

# ── From n02: extract CAT-04 indicators ───────────────────────────────────────
cat04_inds = []
for cat in n02_payload.get('categories', []):
    if cat.get('id') == 'CAT-04':
        cat04_inds = cat.get('indicators', [])
        break

log.info(f"geometry keys        : {list(geometry.keys())}")
log.info(f"special_characteristics: {len(sc_cc)}")
log.info(f"quick_connector keys : {list(qc.keys()) if qc else []}")
log.info(f"cat04_inds (CAT-04)  : {len(cat04_inds)}")
log.info(f"has_3d_model         : {has_3d_model}")
```

---

### Step 2: 构建组件树

#### 2a. 辅助函数定义

```python
log.step("Step 2: Build component tree")

# ── Helper: fuzzy match CAT-04 indicator by keyword in parameter name ─────────
def find_drg(keyword: str):
    """Return first CAT-04 indicator whose parameter name contains keyword (case-insensitive)."""
    kw = keyword.lower()
    for ind in cat04_inds:
        if kw in ind.get('parameter', '').lower():
            return ind
    return None

# ── Helper: parse tolerance string → (nominal, tol_plus, tol_minus) ──────────
def parse_tolerance(val_str):
    """
    Parse strings like '8.0 ± 0.1' or plain '8.0'.
    Returns (nominal: float, tol_plus: float, tol_minus: float).
    tol_plus == tol_minus for symmetric tolerances.
    Returns (None, None, None) on parse failure.
    """
    if val_str is None:
        return None, None, None
    s = str(val_str).strip()
    # Pattern: "8.0 ± 0.1" or "8.0±0.1"
    m = re.match(r'([\d.]+)\s*[±+\-]{1,2}\s*([\d.]+)', s)
    if m:
        nominal  = float(m.group(1))
        tol      = float(m.group(2))
        return nominal, tol, tol
    # Plain number
    try:
        return float(s), None, None
    except ValueError:
        pass
    # 无法解析（如不对称公差 "+0.1/-0.05"）→ 返回 None，需 AI 手动处理
    # log.info(f"parse_tolerance: cannot parse '{s}' — tolerance will be None")
    return None, None, None

# ── Helper: extract Cpk value from design_target text ────────────────────────
def extract_cpk(drg_ind) -> float | None:
    """
    Regex-extract Cpk value from a CAT-04 indicator's design_target text.
    Returns float or None.
    """
    if drg_ind is None:
        return None
    text = drg_ind.get('design_target', '') or ''
    m = re.search(r'Cpk\s*[≥>=]\s*([\d.]+)', text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None

# ── Helper: global counter-based ID generators ───────────────────────────────
_comp_counter = 0
_dim_counter  = 0

def make_comp_id() -> str:
    global _comp_counter
    _comp_counter += 1
    return f"COMP-{_comp_counter:03d}"

def make_dim_id(comp_num: int) -> str:
    # 注意：_dim_counter 全局递增，确保 ID 在整个 artifact 内唯一；
    # NNN 为全局序号而非组件内序号。
    global _dim_counter
    _dim_counter += 1
    return f"DIM-{comp_num:03d}-{_dim_counter:03d}"

# ── Helper: collect SC/CC parameter names matching any keyword ───────────────
def sc_cc_refs_for(*keywords) -> list:
    """
    Return list of SC/CC parameter names where any keyword appears
    in the parameter name (case-insensitive).
    Used to link assembly interfaces to special characteristics.
    """
    results = []
    for sc in sc_cc:
        param = sc.get('parameter', '') or ''
        for kw in keywords:
            if kw.lower() in param.lower():
                results.append(param)
                break
    return results

components = []
```

#### 2b 管体（tube）

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 管体检测与 COMP 创建
#
# 目标：从 geometry 中找出成对的 *_od_mm / *_id_mm 键（表示一根管的外径和内径），
#       为每对创建一个 COMP（type="tube"）。
#
# 过滤规则（通用，不硬编码产品名）：
#   排除含以下字段前缀的键：end_form, damper, engine_hp_port, port_connection
#   理由：这些字段属于其它子组件，由 2c/2d/2e 步骤处理。
#
# 步骤：
#   1. 从 geometry 收集所有形如 *_od_mm 的键，过滤掉排除前缀。
#   2. 对每个 od_key，推断对应的 id_key（将 _od_ 替换为 _id_）。
#   3. 若 id_key 也存在于 geometry，认定为一对管（tube pair）。
#   4. 推断管名称：从 od_key 提取前缀（去掉 _od_mm 后缀），作为 tube name。
#   5. 为每对管调用 make_comp_id() 创建 COMP，调用 make_dim_id() 创建 OD 和 ID 两个 DIM。
#   6. OD DIM：parameter = od_key，nominal/tol_plus/tol_minus 用 parse_tolerance() 解析。
#              drg_ind = find_drg(od_key 前缀)，cpk = extract_cpk(drg_ind)。
#   7. ID DIM：同上，使用 id_key。
#   8. 每个 DIM：confidence = drg_ind['confidence'] if drg_ind else 'S3'
#               needs_review = confidence in ('S3','S4','S5')
#               missing_dimensions = [] （两个维度都有值）
#   9. 追加到 components 列表。
#
# 示例输出结构（一根管）：
# {
#   "id": "COMP-001", "name": "Feed line", "type": "tube",
#   "quantity": 1,
#   "dimensions": [
#     {"id": "DIM-001-001", "parameter": "feed_line_od_mm", "nominal": 8.0,
#      "tol_plus": 0.1, "tol_minus": 0.1, "unit": "mm",
#      "cpk_target": 1.67, "confidence": "S1", "needs_review": false},
#     {"id": "DIM-001-002", "parameter": "feed_line_id_mm", "nominal": 6.0,
#      "tol_plus": 0.1, "tol_minus": 0.1, "unit": "mm",
#      "cpk_target": 1.67, "confidence": "S1", "needs_review": false}
#   ],
#   "missing_dimensions": []
# }
```

#### 2c 端成形（end_form）

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 端成形检测与 COMP 创建
#
# 触发条件：geometry 中包含 'end_form' 键（dict 或有 end_form_* 子键）。
#
# 步骤：
#   1. 从 geometry 提取 end_form 相关键（end_form_od_mm, end_form_id_mm, end_form_length_mm）。
#   2. 调用 make_comp_id() 创建 COMP（type="end_form", quantity=1）。
#   3. 为 OD、ID、Length 各创建一个 DIM（调用 make_dim_id()）。
#      - OD  : parameter="end_form_od_mm",     find_drg("end_form_od")
#      - ID  : parameter="end_form_id_mm",     find_drg("end_form_id")
#      - Length: parameter="end_form_length_mm", find_drg("end_form_length")
#   4. 缺失的维度（对应 geometry 键不存在）加入 missing_dimensions 列表（字符串列表）。
#   5. 追加到 components。
```

#### 2d 减振器（damper）

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 减振器检测与 COMP 创建
#
# 触发条件：geometry 中包含 'damper' 键。
#
# 步骤：
#   1. 从 geometry 提取 damper 相关键（damper_od_mm, damper_width_mm, damper_port_od_mm）。
#   2. 调用 make_comp_id() 创建 COMP（type="damper", quantity=1）。
#   3. 为 OD、Width、Port_OD 各创建一个 DIM：
#      - OD      : parameter="damper_od_mm",      find_drg("damper_od")
#      - Width   : parameter="damper_width_mm",   find_drg("damper_width")
#      - Port_OD : parameter="damper_port_od_mm", find_drg("damper_port")
#   4. 所有 DIM：confidence = 'S2'（减振器尺寸通常来自设计推断），needs_review = True。
#      理由：减振器规格往往在 3D 模型中才有精确尺寸，fallback 模式下为估算。
#   5. 追加到 components。
```

#### 2e 快接头（quick_connector）

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 快接头检测与 COMP 创建
#
# 触发条件：n01 payload 中 quick_connector (qc) 字段存在且非空。
#
# qc 结构示例（通用）：
# {
#   "fuel_filter_side_feed": {"od_mm": 8.0, "color": "blue"},
#   "fuel_filter_side_return": {"od_mm": 10.0, "color": "black"},
#   "engine_bay_side": {"od_mm": 8.0, "color": "blue"}
# }
#
# 步骤：
#   1. 遍历 qc 的每个 key（如 fuel_filter_side_feed, fuel_filter_side_return, engine_bay_side）。
#   2. 若该 key 对应的值非空（filled side），为其创建一个 COMP（type="quick_connector"）。
#   3. DIM：OD（od_mm），find_drg(key + "_od")；
#            若有 insertion_force_n, pull_off_force_n 也创建对应 DIM（unit="N"）。
#   4. 每个 COMP quantity=1，missing_dimensions 列出 qc 子字典中值为 null 的字段。
#   5. 追加到 components。
```

#### 2f 密封件（seal）

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 密封件检测与 COMP 创建
#
# 触发条件：qc 中包含 o_ring_materials 字段（dict 或含 fuel_contact / external 子键）。
#
# 步骤：
#   1. 从 qc['o_ring_materials'] 提取 fuel_contact 和 external O-ring 材料规格。
#   2. 为 fuel_contact O-ring 创建 COMP（type="seal", name="Fuel-contact O-ring"）。
#      DIM：cross_section_mm（find_drg("o_ring_cross")），inner_diameter_mm（find_drg("o_ring_id")）。
#   3. 为 external O-ring 创建 COMP（type="seal", name="External O-ring"）。
#      DIM：同上，使用 external 子字段。
#   4. 材料字段（material）写入 COMP 顶层（非 DIM），供 n05 材料合规节点使用。
#   5. 追加到 components。

log.info(f"Components built: {len(components)}")
for comp in components:
    log.info(f"  {comp['id']} ({comp['type']}): {len(comp['dimensions'])} dims, "
             f"{len(comp.get('missing_dimensions', []))} missing")
```

---

### Step 3: 构建装配接口

```python
log.step("Step 3: Build assembly interfaces")
assembly_interfaces = []
```

> **PSEUDOCODE** — AI 执行时内联实现下方逻辑；不要直接运行此块。

```python
# PSEUDOCODE — 装配接口构建
#
# 装配接口（assembly_interface）描述两个组件之间的配合关系，
# 包括接口类型、配合尺寸引用、以及相关 SC/CC 特性。
#
# assembly_interfaces = []
#
# ── Rule 1：端成形 + 发动机高压口 → quick_connect 接口 ───────────────────────
# 触发条件：components 中存在 type="end_form" 的 COMP，
#           且 geometry 中包含 engine_hp_port 相关键。
#
# 创建接口：
#   {
#     "id": "INTF-001",
#     "type": "quick_connect",
#     "description": "Feed tube end_form → engine HP port quick connection",
#     "from_comp": <end_form COMP id>,
#     "to_component": "engine_hp_port (customer-side)",
#     "mating_dimensions": [<end_form OD DIM id>, <end_form ID DIM id>],
#     "sc_cc_refs": sc_cc_refs_for("leak", "pull-off", "secondary latch"),
#     "needs_review": False
#   }
#
# ── Rule 2：滤清器侧快接头 → quick_connect 接口 ─────────────────────────────
# 触发条件：components 中存在 name 含 "filter_side" 或 "filter side" 的 quick_connector COMP。
#
# 为每个此类 COMP 创建接口：
#   {
#     "id": f"INTF-{n:03d}",
#     "type": "quick_connect",
#     "description": f"Tube → filter side quick connector ({comp['name']})",
#     "from_comp": <tube COMP id，与该接头相配的管>,
#     "to_component": f"{comp['name']} (filter-side port)",
#     "mating_dimensions": [<qc OD DIM id>],
#     "sc_cc_refs": sc_cc_refs_for("leak", "impurities", "cleanliness"),
#     "needs_review": False
#   }
#
# ── Rule 3：减振器 → press_fit 接口 ────────────────────────────────────────
# 触发条件：components 中存在 type="damper" 的 COMP。
#
# 创建接口：
#   {
#     "id": "INTF-xxx",
#     "type": "press_fit",
#     "description": "Tube → damper press-fit assembly",
#     "from_comp": <tube COMP id（主管）>,
#     "to_component": <damper COMP id>,
#     "mating_dimensions": [<damper port_od DIM id>],   # damper_port_connection_od_mm
#     "sc_cc_refs": sc_cc_refs_for("static charge", "ESD"),
#     "needs_review": True    # 减振器接口在无 3D 模型时为推断，需复核
#   }

log.info(f"Assembly interfaces built: {len(assembly_interfaces)}")
for intf in assembly_interfaces:
    log.info(f"  {intf['id']} ({intf['type']}): {intf['description'][:60]}")
```

---

### Step 4: 完整度计算、Gap 识别、写 Artifact

```python
log.step("Step 4: Completeness, gap identification, write artifact")

# ── Completeness calculation ──────────────────────────────────────────────────
total_dims    = sum(len(c.get('dimensions', []))         for c in components)
total_missing = sum(len(c.get('missing_dimensions', [])) for c in components)
completeness_pct = round(total_dims / max(total_dims + total_missing, 1) * 100)

log.info(f"total_dims      : {total_dims}")
log.info(f"total_missing   : {total_missing}")
log.info(f"completeness_pct: {completeness_pct}%")

# ── Dimensions only available from 3D model ───────────────────────────────────
missing_from_3d = [
    "Assembly routing and bend angles",
    "Clip/bracket positions and spacing",
    "Package envelope validation",
]

# ── Gap identification ────────────────────────────────────────────────────────
gaps = []

# R-03-01: geometry empty — cannot build any component tree
if not geometry:
    msg = "n01 geometry is empty — component tree cannot be built"
    log.gap("R-03-01", msg, "error")
    gaps.append({"rule": "R-03-01", "msg": msg, "severity": "error", "assumption": None})

# R-03-02: no 3D model — routing/bend angles/clip positions unknown
if not has_3d_model:
    msg = (f"No 3D model available — {len(missing_from_3d)} geometry aspects cannot be resolved: "
           f"{'; '.join(missing_from_3d)}")
    log.gap("R-03-02", msg, "warning")
    gaps.append({"rule": "R-03-02", "msg": msg, "severity": "warning",
                 "assumption": "Fallback mode: component tree built from n01 geometry + n02 CAT-04"})

# R-03-03: any component has missing_dimensions (design doc: "任意组件 missing_dimensions 非空")
comps_with_missing = [c['id'] for c in components if c.get('missing_dimensions')]
if comps_with_missing:
    msg = (f"{len(comps_with_missing)} component(s) have missing dimensions: {comps_with_missing}")
    log.gap("R-03-03", msg, "warning")
    gaps.append({"rule": "R-03-03", "msg": msg, "severity": "warning",
                 "assumption": "Missing dims only resolvable from 3D model or supplier drawing"})

# R-03-04: SC/CC indicator exists but no corresponding interface record
#   (design doc: "存在 SC/CC 尺寸指标但无对应接口记录")
all_intf_sc_refs = {ref for intf in assembly_interfaces for ref in intf.get('sc_cc_refs', [])}
sc_cc_inds = [ind for ind in n02_cat04_inds if ind.get('sc_cc')]  # SC/CC-flagged n02 indicators
orphan_sc = [ind['id'] for ind in sc_cc_inds if ind['id'] not in all_intf_sc_refs]
if orphan_sc:
    msg = (f"SC/CC indicators with no interface record: {orphan_sc} — "
           "add assembly_interface entry referencing these specs")
    log.gap("R-03-04", msg, "warning")
    gaps.append({"rule": "R-03-04", "msg": msg, "severity": "warning",
                 "assumption": None})

# ── Confidence floor ──────────────────────────────────────────────────────────
all_confidences = [
    dim.get('confidence', 'S1')
    for comp in components
    for dim in comp.get('dimensions', [])
]
valid_confs = [c for c in all_confidences if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S1'

# ── Build final artifact ──────────────────────────────────────────────────────
artifact = {
    "node":            "n03",
    "project":         n01.get("project"),
    "status":          "ready",
    "produced_at":     datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":            gaps,
    "assumptions": [
        "Component tree built from n01 geometry + n02 CAT-04 (fallback mode — no 3D model)",
        "Tube pairs detected by *_od_mm / *_id_mm key pairing in geometry dict",
        "SC/CC refs linked by keyword fuzzy match against special_characteristics",
    ],
    "payload": {
        "geometry_version":   geometry_version,
        "has_3d_model":       has_3d_model,
        "completeness_pct":   completeness_pct,
        "missing_from_3d":    missing_from_3d,
        "components":         components,
        "assembly_interfaces": assembly_interfaces,
    }
}

store.write('n03', artifact)
log.done(artifact)

# ── Write report + print summary ──────────────────────────────────────────────
execution_summary = """
### 处理摘要

| 字段 | 来源 | 条目数 |
|------|------|--------|
| geometry | n01 payload | (key count) |
| special_characteristics | n01 payload | (actual count) |
| quick_connector | n01 payload | (present/absent) |
| cat04_inds | n02 CAT-04 | (actual count) |

### 组件树

(AI 填写每个 COMP 类型、维度数、missing_dimensions)

### 装配接口

(AI 填写每个 INTF 类型和配合关系)

### 假设与判断

- (AI 填写实际推断的组件尺寸及置信度)
"""

report = NodeReport('<project_path>', 'n03')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
# → 报告写入 reports/n03-report-YYYYMMDD-HHMMSS.md
```

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n03')
p = a['payload']

assert a['status'] == 'ready', f"status is '{a['status']}', expected 'ready'"

components = p.get('components', [])
assert components, "components is empty — no component tree was built"

# Every component must have required fields
for comp in components:
    assert 'id'   in comp, f"component missing 'id': {comp}"
    assert 'name' in comp, f"component missing 'name': {comp.get('id')}"
    assert 'type' in comp, f"component missing 'type': {comp.get('id')}"
    assert 'quantity' in comp, f"component missing 'quantity': {comp.get('id')}"
    assert 'dimensions' in comp, f"component missing 'dimensions': {comp.get('id')}"
    assert 'missing_dimensions' in comp, f"component missing 'missing_dimensions': {comp.get('id')}"

# Every dimension must have required fields
for comp in components:
    for dim in comp.get('dimensions', []):
        assert 'id'          in dim, f"dim missing 'id' in {comp.get('id')}: {dim}"
        assert 'parameter'   in dim, f"dim missing 'parameter' in {comp.get('id')}: {dim}"
        assert 'nominal'     in dim, f"dim missing 'nominal' in {comp.get('id')}: {dim}"
        assert 'unit'        in dim, f"dim missing 'unit' in {comp.get('id')}: {dim}"
        assert 'confidence'  in dim, f"dim missing 'confidence' in {comp.get('id')}: {dim}"
        assert 'needs_review' in dim, f"dim missing 'needs_review' in {comp.get('id')}: {dim}"

# Gap rule R-03-02 must be present when no 3D model
gap_rules = [g['rule'] for g in a.get('gaps', [])]
assert 'R-03-02' in gap_rules or p.get('has_3d_model'), \
    "R-03-02 gap missing but has_3d_model=False — no-3D-model gap must always be flagged"

# At least one tube component must exist
tube_comps = [c for c in components if c.get('type') == 'tube']
assert tube_comps, "No tube component found — geometry must contain at least one *_od_mm / *_id_mm pair"

# assembly_interfaces present
assert 'assembly_interfaces' in p, "payload missing 'assembly_interfaces'"

print(f"✓ n03 valid")
print(f"  Component count    : {len(components)}")
comp_types = {}
for c in components:
    comp_types[c['type']] = comp_types.get(c['type'], 0) + 1
for t, n in sorted(comp_types.items()):
    print(f"    {t:<20}: {n}")
print(f"  Assembly interfaces: {len(p['assembly_interfaces'])}")
print(f"  Completeness       : {p['completeness_pct']}%")
print(f"  has_3d_model       : {p['has_3d_model']}")
print(f"  geometry_version   : {p['geometry_version']}")
print(f"  confidence_floor   : {a['confidence_floor']}")
print(f"  Gaps               : {gap_rules}")
```

---

## Optimize Mode

当客户提供了 3D 模型（从 Teamcenter 下载）或补充了更精确的几何数据时：

1. 读取现有 `artifacts/n03-output.json`
2. 用 3D 模型实测值替换 CTS PPTX 推导的尺寸（confidence 从 S3/S4 升到 S1/S2）
3. 更新 components 中受影响的 dimensions（保留未变化的）
4. 设置 `has_3d_model: true`，移除 R-03-02 gap
5. 重新计算 `completeness_pct` 和 `confidence_floor`
6. 更新 `geometry_version`（递增）
7. log 中所有 step 标题加 `[Optimize]` 前缀

**关键**：n03 是扇出枢纽，Optimize 后运行 `orchestrator.py affected n03` — 通常影响 n04–n08 共 5 个直接下游 + 更多间接下游。

---

## Review Mode

仅检查现有 artifact 质量，不修改文件：

1. 读取 `artifacts/n03-output.json`
2. 运行上方 Validation 代码段
3. 输出质量摘要：零件数、completeness_pct、has_3d_model、confidence_floor、gaps
