# NODE-12: Conversion Cost（转化成本/加工费）

**Purpose**: Calculate manufacturing conversion cost per piece from n08 process route (labor + equipment depreciation + overhead).
**Input**: `artifacts/n08-output.json` — operations list with cycle times, operators, investment
**Output**: `artifacts/n12-output.json`
**Type**: auto

---

## Precondition Check

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# 检查上游依赖（network.json: n08 → n12, type=normal）
upstream_ids = ['n08']
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

# 初始化 logger
log = NodeLogger('<project_path>', 'n12')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read n08 process route

```
log.step("Step 1: Read n08 operations list")
```

Read `artifacts/n08-output.json`. Extract from `payload`:
- `operations[]` — each operation with:
  - `op_id`, `op_name`, `process_type`
  - `cycle_time_sec` (seconds per piece)
  - `operators` (number of operators for this operation)
  - `investment_eur` (equipment investment for this operation)
  - `tact_time_sec` (line tact time, may be at summary level)

Also check n08 `assumptions` for any assumed cycle times or investments (these propagate to n12 confidence).

```python
n08 = store.read('n08')
ops = n08['payload']['operations']
log.info(f"n08 operations: {len(ops)}")
for op in ops:
    log.info(f"  {op['op_id']}: {op['op_name']} — cycle={op.get('cycle_time_sec')}s, operators={op.get('operators')}")
```

### Step 2: Establish cost assumptions

```
log.step("Step 2: Establish cost rate assumptions")
```

The following rates are typically assumptions (S3/S4) unless the project provides specific data:

| Parameter | Typical Range | Default Assumption | Confidence |
|-----------|---------------|-------------------|------------|
| `labor_rate_eur_hr` | 25-45 EUR/hr | 35 EUR/hr (Central Europe) | S4 |
| `overhead_rate_pct` | 150-200% of direct labor | 175% | S4 |
| `depreciation_years` | 7-10 years | 8 years | S3 |
| `annual_operating_hours` | 4000-6000 hr/yr | 5000 hr/yr (3-shift) | S3 |

Check if n01 or project.json provides any of these values at higher confidence. If so, use those instead.

```python
# Default assumptions — override with project-specific data if available
labor_rate_eur_hr = 35.0        # S4 assumption
overhead_rate_pct = 175.0       # S4 assumption (% of direct labor)
depreciation_years = 8          # S3 assumption
annual_hours = 5000             # S3 assumption (hours/year)

assumptions = []
assumptions.append({
    "id": "A-12-01", "field": "labor_rate_eur_hr",
    "value": labor_rate_eur_hr, "unit": "EUR/hr",
    "confidence": "S4", "rationale": "Central Europe average, no project-specific data"
})
assumptions.append({
    "id": "A-12-02", "field": "overhead_rate_pct",
    "value": overhead_rate_pct, "unit": "%",
    "confidence": "S4", "rationale": "Industry standard 150-200%, mid-range selected"
})
assumptions.append({
    "id": "A-12-03", "field": "depreciation_years",
    "value": depreciation_years, "unit": "years",
    "confidence": "S3", "rationale": "Standard equipment depreciation period"
})
assumptions.append({
    "id": "A-12-04", "field": "annual_operating_hours",
    "value": annual_hours, "unit": "hr/yr",
    "confidence": "S3", "rationale": "3-shift operation assumption"
})
log.info(f"Cost assumptions established: {len(assumptions)} items")
```

### Step 3: Calculate conversion cost per operation

```
log.step("Step 3: Calculate conversion cost per operation")
```

For each operation in n08:

```
labor_cost_eur     = (cycle_time_sec / 3600) * operators * labor_rate_eur_hr
equipment_cost_eur = investment_eur / (depreciation_years * annual_hours * 3600 / tact_time_sec)
overhead_eur       = labor_cost_eur * (overhead_rate_pct / 100)
total_eur          = labor_cost_eur + equipment_cost_eur + overhead_eur
```

Notes:
- `equipment_cost_eur` denominator = total pieces produced over depreciation life = `depreciation_years * annual_hours * 3600 / tact_time_sec`
- If `tact_time_sec` is not set per operation, use the line-level tact time from n08 summary
- If `investment_eur` is 0 or missing for an operation (e.g., manual assembly), `equipment_cost_eur` = 0

```python
cost_operations = []
total_conversion = 0.0

for op in ops:
    ct = op['cycle_time_sec']
    n_ops = op.get('operators', 1)
    invest = op.get('investment_eur', 0)
    tact = op.get('tact_time_sec') or n08['payload'].get('tact_time_sec', ct)

    labor = (ct / 3600) * n_ops * labor_rate_eur_hr
    if invest > 0 and tact > 0:
        total_pieces_lifetime = depreciation_years * annual_hours * 3600 / tact
        equip = invest / total_pieces_lifetime
    else:
        equip = 0.0
    overhead = labor * (overhead_rate_pct / 100)
    total = labor + equip + overhead

    cost_operations.append({
        "op_ref": op['op_id'],
        "op_name": op['op_name'],
        "cycle_time_sec": ct,
        "operators": n_ops,
        "investment_eur": invest,
        "labor_cost_eur": round(labor, 4),
        "equipment_cost_eur": round(equip, 4),
        "overhead_eur": round(overhead, 4),
        "total_eur": round(total, 4)
    })
    total_conversion += total
    log.info(f"  {op['op_id']}: labor={labor:.4f} equip={equip:.4f} overhead={overhead:.4f} total={total:.4f}")

log.info(f"Total conversion cost per piece: {total_conversion:.4f} EUR")
```

### Step 4: Gap identification

```
log.step("Step 4: Gap identification")
```

| Gap | Rule | Severity | Assumption |
|-----|------|----------|------------|
| Labor rate is assumption (no project data) | R-12-01 | warning | labor_rate_eur_hr value (S4) |
| Investment is estimate (from n08 assumptions) | R-12-02 | info | investment values from n08 |

```python
gaps = []

# R-12-01: labor rate is always an assumption unless customer provides it
gaps.append({
    "rule": "R-12-01",
    "msg": f"Labor rate {labor_rate_eur_hr} EUR/hr is assumption — no project-specific data",
    "severity": "warning",
    "assumption": f"{labor_rate_eur_hr} EUR/hr (S4)"
})

# R-12-02: check if n08 investment values are estimates
n08_assumptions = n08.get('assumptions', [])
invest_assumptions = [a for a in n08_assumptions if 'invest' in a.get('field', '').lower()]
if invest_assumptions:
    gaps.append({
        "rule": "R-12-02",
        "msg": f"Equipment investment values from n08 are estimates ({len(invest_assumptions)} operations)",
        "severity": "info",
        "assumption": "Investment values inherited from n08 assumptions"
    })

log.info(f"Gaps identified: {len(gaps)}")
```

### Step 5: Write artifact

```python
# Determine confidence_floor: worst of all assumptions
# labor_rate = S4, overhead = S4 → floor = S4
conf_values = [a['confidence'] for a in assumptions]
confidence_floor = sorted(conf_values, key=lambda x: int(x[1]), reverse=True)[0]

artifact = {
    "node": "n12",
    "project": "<project_id>",
    "status": "ready",
    "produced_at": "<ISO8601>",
    "confidence_floor": confidence_floor,
    "gaps": gaps,
    "assumptions": assumptions,
    "payload": {
        "operations": cost_operations,
        "summary": {
            "total_conversion_cost_eur": round(total_conversion, 4),
            "labor_rate_assumption": labor_rate_eur_hr,
            "overhead_rate_assumption": overhead_rate_pct,
            "depreciation_years": depreciation_years,
            "annual_operating_hours": annual_hours,
            "operation_count": len(cost_operations)
        }
    }
}
store.write('n12', artifact)
```

### Step 6: Close log

```python
log.done(artifact)
```

### Step 7: Write report

```python
from reporter import NodeReport

# AI 根据本次实际执行情况填写，四个小节不可省略
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n08-output.json` | 工艺路线：工序列表、节拍时间、投资额 |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- **labor_rate_eur_hr**: 35 EUR/hr — 中欧平均水平 (S4)
- **overhead_rate_pct**: 175% — 行业标准范围中值 (S4)
- **depreciation_years**: 8 年 — 标准设备折旧期 (S3)
- **annual_operating_hours**: 5000 hr/yr — 三班制 (S3)

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n12')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Optimize Mode

当用户提供了更精确的数据（替换 S4/S5 假设为 S1/S2 实测值）时：

1. 读取现有 `artifacts/n12-output.json`
2. 初始化 logger，所有 step 标题加 `[Optimize]` 前缀
3. 识别哪些字段被更新（对比新数据 vs 现有 assumptions）
4. 仅更新受影响的字段，保留未变化的部分
5. 重新计算 `confidence_floor`（可能从 S4 升到 S1）
6. 从 `gaps` 和 `assumptions` 中移除已解决的条目
7. 写回 artifact → 关闭日志 → 写报告（同 Build 的 Step 5/6/7）
8. 运行 Validation

Typical optimize scenarios:
- Customer provides actual labor rate → replace A-12-01, remove R-12-01
- Supplier confirms equipment quotes → update investment values, remove R-12-02
- n08 optimized with real cycle times → recalculate all operations

### 何时退回 Build 模式

以下情况说明变更超出了局部更新的范围，必须全量重跑：

- payload 中**新增或删除了顶层 list 条目**（如 n08 增删了工序）
- 上游节点的 **payload 结构发生变化**（n08 新增/删除了字段 key）
- 本节点的 **核心输入来源变了**（如从 n08 假设工艺改为实际工艺路线）
- `confidence_floor` 从 S1/S2 **降级**到 S4/S5（说明数据质量退化，需要重新审视全部逻辑）

如果不确定，选择 Build — 全量重跑比漏更新安全。

---

## Review Mode

仅检查现有 artifact 质量，不修改任何文件：

1. 读取 `artifacts/n12-output.json`
2. 运行下方 Validation 检查
3. 统计：gaps 数量（按 severity）、assumptions 数量、confidence_floor
4. 输出质量摘要，不写 artifact

---

## Validation

```python
# 在 Build/Optimize 完成后运行
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
artifact = store.read('n12')
p = artifact.get('payload', {})

# 1. 必填字段检查
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status 无效"
assert artifact.get('confidence_floor'), "confidence_floor 未设置"

# 2. 节点特有校验
assert len(p.get('operations', [])) > 0, "operations 为空 — 无工序成本数据"

# 验证每个 operation 的必填字段
for op in p['operations']:
    assert op.get('op_ref'), f"operation missing op_ref: {op}"
    assert 'labor_cost_eur' in op, f"operation {op.get('op_ref')} missing labor_cost_eur"
    assert 'equipment_cost_eur' in op, f"operation {op.get('op_ref')} missing equipment_cost_eur"
    assert 'overhead_eur' in op, f"operation {op.get('op_ref')} missing overhead_eur"
    assert 'total_eur' in op, f"operation {op.get('op_ref')} missing total_eur"
    # 验证加法一致性
    expected_total = op['labor_cost_eur'] + op['equipment_cost_eur'] + op['overhead_eur']
    assert abs(op['total_eur'] - expected_total) < 0.01, \
        f"operation {op['op_ref']}: total_eur {op['total_eur']} != sum {expected_total}"

# 验证 summary
s = p.get('summary', {})
assert s.get('total_conversion_cost_eur') is not None, "summary.total_conversion_cost_eur missing"
assert s.get('labor_rate_assumption'), "summary.labor_rate_assumption missing"
assert s.get('overhead_rate_assumption'), "summary.overhead_rate_assumption missing"
assert s.get('depreciation_years'), "summary.depreciation_years missing"

# 验证总和一致性
ops_sum = sum(op['total_eur'] for op in p['operations'])
assert abs(s['total_conversion_cost_eur'] - ops_sum) < 0.01, \
    f"summary total {s['total_conversion_cost_eur']} != operations sum {ops_sum}"

# 3. gaps 完整性：每个 gap 必须有 rule + msg + severity
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap 格式不完整: {g}"

# 4. 检查必须存在的 gap
gap_rules = [g['rule'] for g in artifact.get('gaps', [])]
# R-12-01 should exist unless labor rate is project-confirmed
has_labor_assumption = any(a['field'] == 'labor_rate_eur_hr' and a['confidence'] in ('S3','S4','S5')
                           for a in artifact.get('assumptions', []))
if has_labor_assumption:
    assert 'R-12-01' in gap_rules, "R-12-01 gap missing — labor rate is assumption but gap not flagged"

print(f"✓ n12 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Operations: {len(p['operations'])}")
print(f"  Total conversion cost: {s['total_conversion_cost_eur']:.4f} EUR/piece")
print(f"  Assumptions: {len(artifact.get('assumptions', []))}")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
