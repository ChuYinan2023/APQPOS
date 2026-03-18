# NODE-02: DRG 设计要求指南（Design Requirements Guide）

**Purpose**: Read n01's structured output → translate customer spec clauses into quantified engineering targets, organized into 8 generic categories; flag uncertain/conflicting items for engineer review.
**Input**: `artifacts/n01-output.json`
**Output**: `artifacts/n02-output.json`
**Type**: auto（AI 全自动；待审阅条目需工程师确认后方可进入下游）

---

## Precondition Check

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

n01 = store.read('n01')
assert n01['status'] == 'ready', \
    f"n01 status is '{n01['status']}' — must be 'ready' before running n02"
assert n01['payload'].get('performance_requirements'), \
    "n01 payload.performance_requirements is empty — cannot generate any indicator (R-02-01 error)"

# Start logger — do this ONCE after precondition passes
log = NodeLogger('<project_path>', 'n02')
log.step("Precondition: n01 ready, performance_requirements present")
log.info(f"n01 confidence_floor: {n01['confidence_floor']}")
log.info(f"n01 gaps: {[g['rule'] for g in n01.get('gaps', [])]}")
```

---

## Execution Steps

### Step 1: 读取 n01 Payload

```python
log.step("Step 1: Read n01 payload fields")

payload = n01['payload']

performance_requirements  = payload.get('performance_requirements', [])
test_matrix               = payload.get('test_matrix', [])
special_characteristics   = payload.get('special_characteristics', [])
geometry                  = payload.get('geometry', {})
material_compliance       = payload.get('material_compliance', {})
quality_targets           = payload.get('quality_targets', {})
referenced_standards      = payload.get('referenced_standards', [])

log.info(f"performance_requirements : {len(performance_requirements)}")
log.info(f"test_matrix              : {len(test_matrix)}")
log.info(f"special_characteristics  : {len(special_characteristics)}")
log.info(f"geometry keys            : {list(geometry.keys())}")
log.info(f"material_compliance keys : {list(material_compliance.keys())}")
log.info(f"quality_targets keys     : {list(quality_targets.keys())}")
log.info(f"referenced_standards     : {len(referenced_standards)}")
```

---

### Step 2: 分类 + 量化 + 审阅标注

Each requirement from n01 is processed in three sub-steps:

#### 2a. 归类（Route to category）

Route every item to exactly one of the 8 generic categories based on its semantic content.
Empty categories are **not** included in the output.

**Generic classification rules** (keyword matching is guidance, not hard rules — use semantic judgment):

| CAT ID | Category Name | Keywords / Signals |
|--------|--------------|-------------------|
| CAT-01 | 功能性能 | primary function, operating pressure, flow rate, pull-off force, insertion/extraction force, working load, cycle count, capacity, throughput, rated output |
| CAT-02 | 结构完整性 | burst, tensile strength, pull-off, vibration, fatigue, impact, crush, proof load, creep, deformation, fracture |
| CAT-03 | 环境耐受 | temperature, thermal, corrosion, salt spray, chemical resistance, humidity, UV, weathering, freeze-thaw, fluid compatibility |
| CAT-04 | 尺寸符合性 | tolerance, GD&T, Cpk, dimension, diameter, wall thickness, flatness, runout, positional, interference fit |
| CAT-05 | 材料与合规 | ELV, REACH, IMDS, RoHS, prohibited substances, restricted materials, recycled content, SVHC, halogen-free |
| CAT-06 | 电气/EMC | electrical resistance, conductivity, ESD, EMI, EMC, leakage current, dielectric, insulation, grounding |
| CAT-07 | 质量与可靠性 | reliability target, P99C90, R95C90, sample size, MTBF, PPM target, Cpk target, control plan, warranty |
| CAT-08 | 外观与标识 | appearance, surface finish, color, gloss, roughness, part marking, label, laser etching, packaging, cleanliness |

> **Note**: An item may contain signals from multiple categories. Route it to the category that
> best captures its **primary engineering constraint**. If ambiguous, prefer the more specific category.
> CAT-06 (电气/EMC) should only be populated when n01 explicitly contains electrical/EMC requirements.

#### 2b. 量化（Quantify the requirement）

For each item, attempt to extract a numeric value:

- **If raw text contains a number**: extract `value`, `unit`, `condition`; set `quantified = true`.
- **If purely descriptive** (e.g., "shall be robust", "good appearance"): set `quantified = false`,
  `needs_review = true`, `review_reason = "requirement_descriptive"`.

**Design target translation principle**: Translate the customer requirement into a supplier-side
design action ("what to design/achieve"), not a mere restatement of the spec clause.

- Example: "Burst pressure ≥ 36 bar @RT" → `design_target: "Design to withstand ≥ 36 bar burst at 23 °C; use safety factor ≥ 1.5 in structural analysis"`
- If no design action can be inferred from the requirement text, fill `design_target` with the
  performance target value and set `needs_review = true`.

**Confidence level rules**:

| Situation | confidence | needs_review |
|-----------|-----------|--------------|
| Value directly from spec text (S1 source) | S1 or S2 (inherit from n01) | false (unless conflict) |
| Value inferred from referenced standard not in inputs/ | S3 | true |
| AI-inferred design target without any source value | S5 | true (`review_reason = "low_confidence"`) |

#### 2c. 冲突检测（Conflict detection）

If the same parameter appears in **two or more source documents** (e.g., SSTS and PF spec)
with **different numeric values**:

- Set `needs_review = true`
- Set `review_reason = "conflict"`
- Record both values in `conflict_detail`: `{"sources": [...], "values": [...]}`

> **注意（AI 执行者）**: 下方代码块为伪代码骨架，展示数据结构和处理流程。
> 执行时按步骤 2a/2b/2c 的规则逐条处理，不要直接 import 这些函数。
> 将 `classify_requirement` / `extract_numeric` / `derive_design_target` 的逻辑**内联实现**：
> - `classify_requirement(item)` → 根据 2a 分类表，读取 `item['parameter']` 和描述文本，返回 `"CAT-XX"` 字符串
> - `extract_numeric(item)` → 从 `item['value']` / `item['requirement']` 中提取数字，返回 `(value, unit, condition, quantified)`
> - `derive_design_target(item, value, unit)` → 将客户需求翻译为供应商侧设计动作（见 2b），返回字符串或 None

```python
# PSEUDOCODE — AI 执行时内联实现 classify_requirement / extract_numeric / derive_design_target
log.step("Step 2: Classify, quantify, flag review items")

# Indicator ID counter
# 注意：计数器全局递增（跨分类），确保 ID 在整个 artifact 内唯一。
# ID 格式 IND-CAT-XX-NNN 中 NNN 为全局序号，不重置。
indicator_counter = 0

def make_id(cat_id: str) -> str:
    global indicator_counter
    indicator_counter += 1
    return f"IND-{cat_id}-{indicator_counter:03d}"

# categories_dict: {cat_id: {"id": ..., "name": ..., "indicators": [...]}}
categories_dict = {}

CAT_META = {
    "CAT-01": "功能性能",
    "CAT-02": "结构完整性",
    "CAT-03": "环境耐受",
    "CAT-04": "尺寸符合性",
    "CAT-05": "材料与合规",
    "CAT-06": "电气/EMC",
    "CAT-07": "质量与可靠性",
    "CAT-08": "外观与标识",
}

def add_indicator(cat_id: str, indicator: dict):
    if cat_id not in categories_dict:
        categories_dict[cat_id] = {
            "id": cat_id,
            "name": CAT_META[cat_id],
            "indicators": []
        }
    categories_dict[cat_id]["indicators"].append(indicator)

# ── Process performance_requirements ─────────────────────────────────────────
# For each item, route to category, extract value/unit, set needs_review flags.
# Example skeleton (AI fills actual logic per item):
for req in performance_requirements:
    cat_id = classify_requirement(req)          # AI judgment using table above
    value, unit, condition, quantified = extract_numeric(req)
    needs_review = not quantified
    review_reason = "requirement_descriptive" if not quantified else None
    confidence = req.get('confidence', 'S2')
    design_target = derive_design_target(req, value, unit)
    if design_target is None:
        needs_review = True
        review_reason = review_reason or "low_confidence"
        confidence = "S5"
        design_target = f"{req.get('value','')} {req.get('unit','')}".strip()

    ind = {
        "id":            make_id(cat_id),
        "parameter":     req.get('parameter'),
        "source_n01":    req.get('id'),
        "source_doc":    req.get('source_doc'),
        "raw_text":      req.get('value', ''),
        "value":         value,
        "unit":          unit,
        "condition":     condition,
        "design_target": design_target,
        "quantified":    quantified,
        "needs_review":  needs_review,
        "review_reason": review_reason,
        "confidence":    confidence,
        "conflict":      False,
        "conflict_detail": None,
        "dfmea_correction": None,
    }
    add_indicator(cat_id, ind)

# ── Process special_characteristics → CAT-04 or CAT-02 ───────────────────────
for sc in special_characteristics:
    cat_id = classify_requirement(sc)  # SC/CC 通常归 CAT-04（尺寸）或 CAT-02（结构）
    value, unit, condition, quantified = extract_numeric(sc)
    design_target = derive_design_target(sc, value, unit)
    if design_target is None:
        quantified = False
        design_target = f"{sc.get('requirement', '')}".strip() or str(value)
    ind = {
        "id":                make_id(cat_id),
        "parameter":         sc.get("parameter", sc.get("description", "")),
        "requirement_raw":   sc.get("requirement", ""),
        "design_target":     design_target,
        "quantified":        quantified,
        "value":             value,
        "unit":              unit,
        "condition":         condition,
        "test_ref":          sc.get("source_section", ""),
        "acceptance_criteria": sc.get("acceptance_criteria", ""),
        "source_n01":        f"special_characteristics[{sc.get('id', '')}]",
        "source_doc":        sc.get("source_doc"),
        "confidence":        sc.get("confidence", "S1"),   # SC/CC are typically S1
        "needs_review":      not quantified,
        "review_reason":     "requirement_descriptive" if not quantified else None,
        "conflict":          False,
        "conflict_detail":   None,
        "dfmea_correction":  None,
    }
    add_indicator(cat_id, ind)

# ── Process geometry → CAT-04 ────────────────────────────────────────────────
if geometry:
    for dim_key, dim_val in geometry.items():
        if dim_key == 'confidence':
            continue
        ind = {
            "id":            make_id("CAT-04"),
            "parameter":     dim_key,
            "source_n01":    "geometry",
            "source_doc":    geometry.get('source_doc'),
            "raw_text":      str(dim_val),
            "value":         dim_val if isinstance(dim_val, (int, float)) else None,
            "unit":          "mm",
            "condition":     None,
            "design_target": f"Maintain {dim_key} = {dim_val} mm within drawing tolerance; target Cpk ≥ 1.67",
            "quantified":    isinstance(dim_val, (int, float)),
            "needs_review":  not isinstance(dim_val, (int, float)),
            "review_reason": "requirement_descriptive" if not isinstance(dim_val, (int, float)) else None,
            "confidence":    geometry.get('confidence', 'S1'),
            "conflict":      False,
            "conflict_detail": None,
            "dfmea_correction": None,
        }
        add_indicator("CAT-04", ind)

# ── Process material_compliance → CAT-05 ─────────────────────────────────────
if material_compliance:
    restricted = material_compliance.get('restricted', [])
    standards  = material_compliance.get('standards', [])
    ind = {
        "id":            make_id("CAT-05"),
        "parameter":     "Restricted substances compliance",
        "source_n01":    "material_compliance",
        "source_doc":    "n01",
        "raw_text":      f"Restricted: {restricted}; Standards: {standards}",
        "value":         None,
        "unit":          None,
        "condition":     None,
        "design_target": f"Ensure all materials comply with {', '.join(standards)}; exclude {', '.join(restricted)}; submit IMDS",
        "quantified":    False,
        "needs_review":  not bool(standards),
        "review_reason": "requirement_descriptive" if not standards else None,
        "confidence":    material_compliance.get('confidence', 'S1'),
        "conflict":      False,
        "conflict_detail": None,
        "dfmea_correction": None,
    }
    add_indicator("CAT-05", ind)

# ── Process quality_targets → CAT-07 ─────────────────────────────────────────
if quality_targets:
    for qk, qv in quality_targets.items():
        if qk in ('confidence',):
            continue
        quantified = isinstance(qv, (int, float, str)) and any(c.isdigit() for c in str(qv))
        ind = {
            "id":            make_id("CAT-07"),
            "parameter":     qk,
            "source_n01":    "quality_targets",
            "source_doc":    "n01",
            "raw_text":      str(qv),
            "value":         qv if isinstance(qv, (int, float)) else None,
            "unit":          None,
            "condition":     None,
            "design_target": f"Design verification plan must demonstrate {qk} = {qv}",
            "quantified":    quantified,
            "needs_review":  not quantified,
            "review_reason": "requirement_descriptive" if not quantified else None,
            "confidence":    "S1",
            "conflict":      False,
            "conflict_detail": None,
            "dfmea_correction": None,
        }
        add_indicator("CAT-07", ind)

log.info(f"Categories populated: {list(categories_dict.keys())}")
for cat_id, cat in categories_dict.items():
    log.info(f"  {cat_id} ({cat['name']}): {len(cat['indicators'])} indicators")
```

---

### Step 3: n07 DFMEA 反馈（可选，仅第二次运行时执行）

If n07-output.json exists and contains `dfmea_corrections`, update affected indicators and
increment `drg_version`. This step is skipped silently on the first run.

```python
log.step("Step 3: n07 DFMEA feedback (optional)")

drg_version = 1

try:
    n07 = store.read('n07')
    corrections = n07.get('payload', {}).get('dfmea_corrections', [])
    if corrections:
        drg_version += 1
        log.info(f"n07 dfmea_corrections found: {len(corrections)} items — incrementing drg_version to {drg_version}")
        for corr in corrections:
            target_id = corr.get('indicator_id')
            for cat in categories_dict.values():
                for ind in cat['indicators']:
                    if ind['id'] == target_id:
                        old_target = ind['design_target']
                        ind['design_target'] = corr.get('revised_design_target', old_target)
                        ind['dfmea_correction'] = {
                            "corrected_by": "n07",
                            "original_design_target": old_target,
                            "dfmea_finding": corr.get('finding'),
                        }
                        ind['needs_review'] = True
                        ind['review_reason'] = ind.get('review_reason') or "dfmea_correction"
                        log.info(f"  Updated {target_id}: {corr.get('finding')}")
    else:
        log.info("n07 found but no dfmea_corrections — no changes applied")
except Exception:
    log.info("n07 not available — skipping")
```

---

### Step 4: 汇总、Gap 识别、写 Artifact

```python
log.step("Step 4: Summarize, gap identification, write artifact")

# ── Build review_items list ───────────────────────────────────────────────────
review_items = []
conflict_count = 0

for cat in categories_dict.values():
    for ind in cat['indicators']:
        if ind.get('needs_review'):
            review_items.append({
                "indicator_id":  ind['id'],
                "parameter":     ind['parameter'],
                "review_reason": ind.get('review_reason'),
                "confidence":    ind.get('confidence'),
                "conflict_detail": ind.get('conflict_detail'),
            })
            if ind.get('review_reason') == 'conflict':
                conflict_count += 1

review_required_count = len(review_items)
log.info(f"review_required_count : {review_required_count}")
log.info(f"conflict_count        : {conflict_count}")

# ── Total indicator count ─────────────────────────────────────────────────────
total_indicators = sum(len(c['indicators']) for c in categories_dict.values())
log.info(f"total indicators      : {total_indicators}")

# ── Gap identification ────────────────────────────────────────────────────────
gaps = []

# R-02-01 (error): performance_requirements empty → cannot generate any indicator
if not performance_requirements:
    log.gap("R-02-01",
            "performance_requirements empty — n02 cannot generate any design indicator",
            "error")
    gaps.append({"rule": "R-02-01",
                 "msg": "performance_requirements empty — n02 cannot generate any design indicator",
                 "severity": "error", "assumption": None})

# R-02-02 (warning): review_required_count > 0
if review_required_count > 0:
    log.gap("R-02-02",
            f"{review_required_count} indicator(s) need engineer review before downstream use",
            "warning")
    gaps.append({"rule": "R-02-02",
                 "msg": f"{review_required_count} indicator(s) need engineer review before downstream use",
                 "severity": "warning", "assumption": None})

# R-02-03 (warning): conflict_count > 0
if conflict_count > 0:
    log.gap("R-02-03",
            f"{conflict_count} parameter(s) have conflicting values from multiple sources",
            "warning")
    gaps.append({"rule": "R-02-03",
                 "msg": f"{conflict_count} parameter(s) have conflicting values from multiple sources",
                 "severity": "warning", "assumption": None})

# R-02-04 (warning): geometry present in n01 but CAT-04 empty
if geometry and 'CAT-04' not in categories_dict:
    log.gap("R-02-04",
            "n01 has geometry data but CAT-04 (尺寸符合性) is empty — check classification logic",
            "warning")
    gaps.append({"rule": "R-02-04",
                 "msg": "n01 has geometry data but CAT-04 (尺寸符合性) is empty — check classification logic",
                 "severity": "warning", "assumption": None})

# ── Compute confidence_floor ──────────────────────────────────────────────────
all_confidences = [ind.get('confidence', 'S2')
                   for cat in categories_dict.values()
                   for ind in cat['indicators']]
confidence_floor = max(all_confidences, key=lambda s: int(s[1:])) if all_confidences else 'S1'

# ── Build final artifact ──────────────────────────────────────────────────────
categories_list = [
    {
        "id":         cat["id"],
        "name":       cat["name"],
        "indicators": cat["indicators"],
    }
    for cat in sorted(categories_dict.values(), key=lambda c: c["id"])
]

artifact = {
    "node":            "n02",
    "project":         n01.get("project"),
    "status":          "ready",
    "produced_at":     datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":            gaps,
    "assumptions":     [],
    "payload": {
        "drg_version":          drg_version,
        "review_required_count": review_required_count,
        "conflict_count":        conflict_count,
        "review_items":          review_items,
        "categories":            categories_list,  # only non-empty categories
    }
}

store.write('n02', artifact)
log.done(artifact)

# ── Write report + print summary ──────────────────────────────────────────────
from reporter import NodeReport

execution_summary = """
### 处理摘要

| 字段 | 来源 | 条目数 |
|------|------|--------|
| performance_requirements | n01 payload | (actual count) |
| special_characteristics  | n01 payload | (actual count) |
| geometry                 | n01 payload | (key count)    |
| material_compliance      | n01 payload | (present/absent) |
| quality_targets          | n01 payload | (key count)    |

### 分类结果

(AI 填写每个 CAT-xx 的条目数及典型示例)

### 审阅项

(AI 列出 needs_review=true 的条目及原因)

### 假设与判断

- (AI 填写实际推断的 design_target 及置信度)
"""

report = NodeReport('<project_path>', 'n02')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
# → 报告写入 reports/n02-report-YYYYMMDD-HHMMSS.md
```

**Artifact payload schema reference:**

```json
{
  "drg_version": 1,
  "review_required_count": 3,
  "conflict_count": 1,
  "review_items": [
    {
      "indicator_id": "IND-CAT-01-001",
      "parameter": "Operating pressure",
      "review_reason": "conflict",
      "confidence": "S2",
      "conflict_detail": {
        "sources": ["SSTS §4.2", "PF.90197 §6.1"],
        "values": ["4.5 bar", "5.0 bar"]
      }
    }
  ],
  "categories": [
    {
      "id": "CAT-01",
      "name": "功能性能",
      "indicators": [
        {
          "id": "IND-CAT-01-001",
          "parameter": "Operating pressure",
          "source_n01": "PR-001",
          "source_doc": "PF.90197",
          "raw_text": "≥ 4.5 bar",
          "value": 4.5,
          "unit": "bar",
          "condition": "nominal",
          "design_target": "Design system to sustain ≥ 4.5 bar continuous operating pressure; structural safety factor ≥ 2.5",
          "quantified": true,
          "needs_review": false,
          "review_reason": null,
          "confidence": "S1"
        }
      ]
    }
  ]
}
```

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n02')
p = a['payload']

assert a['status'] == 'ready', f"status is '{a['status']}', expected 'ready'"

categories = p.get('categories', [])
assert categories, "categories is empty — no indicators were generated"

# Count all indicators
all_indicators = [ind for cat in categories for ind in cat.get('indicators', [])]
assert len(all_indicators) > 0, "total indicator count is 0"

# Check required fields on every indicator
for ind in all_indicators:
    assert 'id'           in ind, f"indicator missing 'id': {ind}"
    assert 'parameter'    in ind, f"indicator missing 'parameter': {ind.get('id')}"
    assert 'source_n01'   in ind, f"indicator missing 'source_n01': {ind.get('id')}"
    assert isinstance(ind.get('needs_review'), bool), \
        f"'needs_review' must be bool: {ind.get('id')}"
    assert isinstance(ind.get('quantified'), bool), \
        f"'quantified' must be bool: {ind.get('id')}"

# review_required_count must match actual count of needs_review=true indicators
actual_review_count = sum(1 for ind in all_indicators if ind.get('needs_review'))
assert p['review_required_count'] == actual_review_count, \
    f"review_required_count={p['review_required_count']} but actual needs_review=true count={actual_review_count}"

# No category with empty indicators list should appear in output
for cat in categories:
    assert cat.get('indicators'), \
        f"Category {cat.get('id')} has empty indicators list — should be omitted from output"

# R-02-02 must be in gap_rules when review_required_count > 0
gap_rules = [g['rule'] for g in a.get('gaps', [])]
if p['review_required_count'] > 0:
    assert 'R-02-02' in gap_rules, \
        f"R-02-02 gap missing but review_required_count={p['review_required_count']}"

print(f"✓ n02 valid")
print(f"  Indicator count  : {len(all_indicators)}")
print(f"  Category count   : {len(categories)}")
print(f"  Review count     : {p['review_required_count']}")
print(f"  Conflict count   : {p['conflict_count']}")
print(f"  drg_version      : {p['drg_version']}")
print(f"  confidence_floor : {a['confidence_floor']}")
print(f"  Gaps             : {gap_rules}")
```

---

## Optimize Mode

当上游 n01 更新后（如新增性能规范、补充测试矩阵），或收到 n07 DFMEA 反馈边时：

1. 读取现有 `artifacts/n02-output.json`
2. 对比上游 n01 的变更字段（performance_requirements、test_matrix、referenced_standards）
3. 仅对受影响的 DRG 类别重新提取指标
4. 合并新指标到现有 categories 中，保留未变化的指标
5. 重新计算 `review_required_count` 和 `conflict_count`
6. 更新 `confidence_floor`，移除已解决的 gaps
7. log 中所有 step 标题加 `[Optimize]` 前缀

**DFMEA 反馈**：n07 → n02 是 feedback 边。当 DFMEA 发现新风险时，需要在 n02 中新增对应指标（needs_review=true）。

---

## Review Mode

仅检查现有 artifact 质量，不修改文件：

1. 读取 `artifacts/n02-output.json`
2. 运行上方 Validation 代码段
3. 输出质量摘要：指标总数、待审核数、冲突数、confidence_floor
