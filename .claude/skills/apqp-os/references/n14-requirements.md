# NODE-14: Project Plan（项目计划）

**Purpose**: Create project milestone plan from n01 deliverables, SOP date, and program phases.
**Input**: `artifacts/n01-output.json` — `deliverables_required`, `sop_date`, `tko_date`, `quality_targets`
**Output**: `artifacts/n14-output.json`
**Type**: mixed (AI generates initial plan, human reviews/adjusts dates)

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

# 检查上游依赖（network.json: n01 → n14, type=secondary）
upstream_ids = ['n01']
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
log = NodeLogger('<project_path>', 'n14')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read n01 project data

```
log.step("Step 1: Read n01 project data")
```

Read `artifacts/n01-output.json`. Extract from `payload`:
- `deliverables_required[]` — list of deliverables with `id`, `name`, `phase`
- `sop_date` — may be `null` (triggers R-14-01)
- `tko_date` — may be `null`
- `rfq_response_date` — if available
- `quality_targets` — reliability, PPM, Cpk targets
- `oem` — determines phase naming conventions

```python
n01 = store.read('n01')
payload = n01['payload']
deliverables = payload.get('deliverables_required', [])
sop_date = payload.get('sop_date')       # may be None
tko_date = payload.get('tko_date')       # may be None
rfq_date = payload.get('rfq_response_date')
quality_targets = payload.get('quality_targets', {})
oem = payload.get('oem', 'unknown')

log.info(f"Deliverables from n01: {len(deliverables)}")
log.info(f"SOP date: {sop_date or 'UNKNOWN'}")
log.info(f"TKO date: {tko_date or 'UNKNOWN'}")
log.info(f"OEM: {oem}")
```

### Step 2: Define program phases

```
log.step("Step 2: Define program phases and timeline")
```

Standard APQP program phases (adapt naming to OEM conventions):

| Phase | Description | Typical Duration | Key Gate |
|-------|-------------|-----------------|----------|
| SOURCING | RFQ response, supplier selection | 4-8 weeks | Nomination |
| TKO | Tool kick-off, design freeze | 8-12 weeks | Design freeze |
| DV | Design validation, prototype build | 12-16 weeks | DV complete |
| PV | Process validation, PPAP prep | 8-12 weeks | PV complete |
| SOP | Start of production ramp-up | 4-8 weeks | SOP gate |

If `sop_date` is known, back-calculate phase boundaries:
```
SOP gate      = sop_date
PV complete   = sop_date - 4 weeks
PV start      = sop_date - 16 weeks
DV complete   = PV start
DV start      = DV complete - 16 weeks
TKO gate      = DV start
TKO start     = tko_date or (TKO gate - 12 weeks)
SOURCING end  = TKO start
SOURCING start = rfq_date or (SOURCING end - 8 weeks)
```

If `sop_date` is `null`, all `target_date` fields are set to `null` and R-14-01 is raised.

```python
from datetime import datetime, timedelta

phases = ['SOURCING', 'TKO', 'DV', 'PV', 'SOP']
phase_boundaries = {}

if sop_date:
    sop_dt = datetime.fromisoformat(sop_date)
    phase_boundaries = {
        'SOP':      {'start': sop_dt - timedelta(weeks=8),  'end': sop_dt},
        'PV':       {'start': sop_dt - timedelta(weeks=20), 'end': sop_dt - timedelta(weeks=8)},
        'DV':       {'start': sop_dt - timedelta(weeks=36), 'end': sop_dt - timedelta(weeks=20)},
        'TKO':      {'start': sop_dt - timedelta(weeks=48), 'end': sop_dt - timedelta(weeks=36)},
        'SOURCING': {'start': sop_dt - timedelta(weeks=56), 'end': sop_dt - timedelta(weeks=48)},
    }
    log.info("Phase boundaries calculated from SOP date")
else:
    log.warn("SOP date unknown — milestones will have no dates")
```

### Step 3: Generate milestones

```
log.step("Step 3: Generate milestones from deliverables")
```

Create milestones by grouping deliverables into their phases. Each milestone represents a gate or deliverable due point.

Rules:
1. Every deliverable in `deliverables_required` must be assigned to exactly one milestone
2. Phase gates (Nomination, Design Freeze, DV Complete, PV Complete, SOP Gate) are always created even if no explicit deliverable maps to them
3. Milestones within a phase are ordered by logical dependency
4. `target_date` is `null` if `sop_date` is unknown

```python
milestones = []
milestone_id = 0
assigned_deliverables = set()

# Phase gate milestones (always present)
gate_milestones = {
    'SOURCING': {'name': 'Supplier Nomination', 'offset_weeks': -48},
    'TKO':      {'name': 'Design Freeze / Tool Kick-Off', 'offset_weeks': -36},
    'DV':       {'name': 'DV Testing Complete', 'offset_weeks': -20},
    'PV':       {'name': 'PV / PPAP Approval', 'offset_weeks': -8},
    'SOP':      {'name': 'Start of Production', 'offset_weeks': 0},
}

for phase in phases:
    # Add phase gate milestone
    milestone_id += 1
    gate = gate_milestones[phase]
    target_date = None
    if sop_date:
        target_date = (sop_dt + timedelta(weeks=gate['offset_weeks'])).strftime('%Y-%m-%d')

    gate_ms = {
        "milestone_id": f"MS-{milestone_id:02d}",
        "name": gate['name'],
        "phase": phase,
        "target_date": target_date,
        "deliverables": [],
        "responsible": "supplier",
        "status": "planned"
    }

    # Assign deliverables to this phase
    phase_deliverables = [d for d in deliverables
                          if d.get('phase', '').upper() == phase
                          and d.get('id') not in assigned_deliverables]
    for d in phase_deliverables:
        gate_ms['deliverables'].append(d['id'])
        assigned_deliverables.add(d['id'])

    milestones.append(gate_ms)

# Check for unassigned deliverables (phase not matching any standard phase)
unassigned = [d for d in deliverables if d.get('id') not in assigned_deliverables]
if unassigned:
    # Create catch-all milestone or assign to closest phase
    for d in unassigned:
        log.warn(f"Deliverable {d['id']} ({d.get('name')}) has no phase match — assigned to TKO")
        # Find TKO milestone and add
        for ms in milestones:
            if ms['phase'] == 'TKO':
                ms['deliverables'].append(d['id'])
                assigned_deliverables.add(d['id'])
                break

log.info(f"Milestones generated: {len(milestones)}")
log.info(f"Deliverables assigned: {len(assigned_deliverables)}/{len(deliverables)}")
```

### Step 4: Gap identification

```
log.step("Step 4: Gap identification")
```

| Gap | Rule | Severity | Assumption |
|-----|------|----------|------------|
| `sop_date` unknown — milestones have no dates | R-14-01 | warning | milestone dates are null |
| Deliverable without milestone assignment | R-14-02 | warning | lists unassigned deliverable IDs |

```python
gaps = []

# R-14-01: SOP date unknown
if not sop_date:
    gaps.append({
        "rule": "R-14-01",
        "msg": "sop_date unknown — all milestone target_date fields are null",
        "severity": "warning",
        "assumption": "No dates assigned; plan is phase-ordered only"
    })

# R-14-02: deliverables without milestone assignment
still_unassigned = [d['id'] for d in deliverables if d.get('id') not in assigned_deliverables]
if still_unassigned:
    gaps.append({
        "rule": "R-14-02",
        "msg": f"{len(still_unassigned)} deliverable(s) without milestone assignment: {', '.join(still_unassigned)}",
        "severity": "warning",
        "assumption": "Unassigned deliverables need manual phase assignment"
    })

log.info(f"Gaps identified: {len(gaps)}")
```

### Step 5: Write artifact

```python
assumptions = []
if not sop_date:
    assumptions.append({
        "id": "A-14-01", "field": "sop_date",
        "value": None, "unit": "date",
        "confidence": "S5", "rationale": "SOP date not provided in RFQ — no timeline can be calculated"
    })

# Confidence floor: S5 if no dates, S3 if dates from RFQ (OEM stated but not confirmed)
if sop_date:
    confidence_floor = "S3"
else:
    confidence_floor = "S5"

artifact = {
    "node": "n14",
    "project": "<project_id>",
    "status": "ready",
    "produced_at": "<ISO8601>",
    "confidence_floor": confidence_floor,
    "gaps": gaps,
    "assumptions": assumptions,
    "payload": {
        "milestones": milestones,
        "summary": {
            "total_milestones": len(milestones),
            "phases_covered": list(set(ms['phase'] for ms in milestones)),
            "sop_date_known": sop_date is not None,
            "sop_date": sop_date,
            "tko_date": tko_date,
            "total_deliverables_assigned": len(assigned_deliverables),
            "total_deliverables_in_n01": len(deliverables)
        }
    }
}
store.write('n14', artifact)
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
| — | `artifacts/n01-output.json` | 交付物清单、SOP日期、TKO日期、质量目标 |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- **sop_date**: 未提供则所有里程碑无日期 (S5)
- **phase_durations**: 基于行业标准APQP阶段时长 (S3)

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n14')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Optimize Mode

当用户提供了更精确的数据（替换 S4/S5 假设为 S1/S2 实测值）时：

1. 读取现有 `artifacts/n14-output.json`
2. 初始化 logger，所有 step 标题加 `[Optimize]` 前缀
3. 识别哪些字段被更新（对比新数据 vs 现有 assumptions）
4. 仅更新受影响的字段，保留未变化的部分
5. 重新计算 `confidence_floor`（可能从 S5 升到 S3）
6. 从 `gaps` 和 `assumptions` 中移除已解决的条目
7. 写回 artifact → 关闭日志 → 写报告（同 Build 的 Step 5/6/7）
8. 运行 Validation

Typical optimize scenarios:
- Customer confirms SOP date → recalculate all target_dates, remove R-14-01, remove A-14-01
- Customer adjusts phase durations → update phase_boundaries and milestone dates
- New deliverables added in n01 optimize → assign to milestones, check R-14-02

### 何时退回 Build 模式

以下情况说明变更超出了局部更新的范围，必须全量重跑：

- payload 中**新增或删除了顶层 list 条目**（如新增了里程碑或删除了整个阶段）
- 上游节点的 **payload 结构发生变化**（n01 deliverables_required 结构变更）
- 本节点的 **核心输入来源变了**（如从 n01 切换到客户提供的独立项目计划）
- `confidence_floor` 从 S1/S2 **降级**到 S4/S5（说明数据质量退化，需要重新审视全部逻辑）

如果不确定，选择 Build — 全量重跑比漏更新安全。

---

## Review Mode

仅检查现有 artifact 质量，不修改任何文件：

1. 读取 `artifacts/n14-output.json`
2. 运行下方 Validation 检查
3. 统计：gaps 数量（按 severity）、assumptions 数量、confidence_floor
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
artifact = store.read('n14')
p = artifact.get('payload', {})

# 1. 必填字段检查
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status 无效"
assert artifact.get('confidence_floor'), "confidence_floor 未设置"

# 2. 节点特有校验
milestones = p.get('milestones', [])
assert len(milestones) > 0, "milestones 为空 — 无里程碑数据"

# 验证每个 milestone 的必填字段
valid_phases = {'SOURCING', 'TKO', 'DV', 'PV', 'SOP'}
for ms in milestones:
    assert ms.get('milestone_id'), f"milestone missing milestone_id: {ms}"
    assert ms.get('name'), f"milestone {ms.get('milestone_id')} missing name"
    assert ms.get('phase') in valid_phases, \
        f"milestone {ms['milestone_id']} has invalid phase: {ms.get('phase')}"
    assert ms.get('status') in ('planned', 'in_progress', 'completed', 'delayed'), \
        f"milestone {ms['milestone_id']} has invalid status: {ms.get('status')}"
    assert 'deliverables' in ms, f"milestone {ms['milestone_id']} missing deliverables list"

# 验证 summary
s = p.get('summary', {})
assert s.get('total_milestones') == len(milestones), \
    f"summary.total_milestones {s.get('total_milestones')} != actual {len(milestones)}"
assert 'sop_date_known' in s, "summary.sop_date_known missing"
assert len(s.get('phases_covered', [])) >= 3, \
    f"Only {len(s.get('phases_covered', []))} phases covered — expected ≥3"

# 验证所有 n01 deliverables 都被分配
all_assigned = set()
for ms in milestones:
    all_assigned.update(ms.get('deliverables', []))
# Read n01 to cross-check
n01 = store.read('n01')
if n01:
    n01_deliverables = {d['id'] for d in n01['payload'].get('deliverables_required', [])}
    unassigned = n01_deliverables - all_assigned
    if unassigned:
        print(f"⚠ {len(unassigned)} n01 deliverables not assigned to any milestone: {unassigned}")

# 日期一致性检查
if s.get('sop_date_known'):
    dates_present = [ms for ms in milestones if ms.get('target_date')]
    assert len(dates_present) == len(milestones), \
        f"SOP date is known but {len(milestones) - len(dates_present)} milestones have no target_date"
else:
    # All dates should be null
    dates_present = [ms for ms in milestones if ms.get('target_date')]
    if dates_present:
        print(f"⚠ SOP date unknown but {len(dates_present)} milestones have target_date — inconsistent")

# 3. gaps 完整性：每个 gap 必须有 rule + msg + severity
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap 格式不完整: {g}"

# 4. 检查必须存在的 gap
gap_rules = [g['rule'] for g in artifact.get('gaps', [])]
if not s.get('sop_date_known'):
    assert 'R-14-01' in gap_rules, "R-14-01 gap missing — sop_date unknown but gap not flagged"

print(f"✓ n14 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Milestones: {len(milestones)}")
print(f"  Phases covered: {s.get('phases_covered', [])}")
print(f"  SOP date known: {s.get('sop_date_known')}")
print(f"  Deliverables assigned: {len(all_assigned)}")
print(f"  Assumptions: {len(artifact.get('assumptions', []))}")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
