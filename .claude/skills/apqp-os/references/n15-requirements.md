# NODE-15: EDD（工程开发费 / Engineering Development & Design Costs）

**Purpose**: Estimate non-recurring engineering costs: tooling, fixtures, DV/PV testing, prototypes, qualification, and project management.
**Input**: `artifacts/n09-output.json` (DVPR — test items with cost estimates), `artifacts/n14-output.json` (project plan — milestones, timeline)
**Output**: `artifacts/n15-output.json`
**Type**: mixed (AI aggregates cost items from upstream data; cost engineer reviews estimates and adds missing items)

---

## Precondition Check

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

_APQPOS = next(p for p in [Path.cwd()] + list(Path.cwd().parents)
               if (p / '.claude/skills/apqp-os/scripts').exists())
sys.path.insert(0, str(_APQPOS / '.claude/skills/apqp-os/scripts'))
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# n15 upstream edges (from network.json):
#   n09 → n15 (normal)  — DVPR with test items and cost estimates
#   n14 → n15 (normal)  — project plan with milestones and timeline
upstream_ids = ['n09', 'n14']
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

# Also read n08 transitively for tooling/fixture investment data
n08 = store.read('n08')
if n08 and n08['status'] in ('ready', 'done'):
    log_n08 = "available"
else:
    log_n08 = "unavailable — tooling estimates will use n09 data only"

log = NodeLogger('<project_path>', 'n15')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
log.info(f"n08 (transitive): {log_n08}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read upstream artifacts — DVPR test costs, project plan, tooling data")
```

1. **Read n09 DVPR** (`artifacts/n09-output.json`):
   - `payload.test_items` or `payload.dvpr_items` — each with:
     - `test_name`, `test_type` (DV / PV), `sample_count`, `estimated_cost_eur`
     - `test_standard`, `lab` (internal / external)
   - Aggregate DV testing costs and PV testing costs separately

2. **Read n14 Project Plan** (`artifacts/n14-output.json`):
   - `payload.milestones` — SOP date, PPAP date, prototype dates
   - `payload.timeline_months` — project duration (affects project management cost)
   - `payload.phases` — APQP phases with start/end dates

3. **Read n08 Process Route** (transitive, if available):
   - `payload.operations` — `equipment_investment_eur` for tooling cost items
   - `payload.total_investment_eur` — aggregate tooling investment

```python
n09 = store.read('n09')
n14 = store.read('n14')
n09_payload = n09['payload']
n14_payload = n14['payload']

# DVPR test items
test_items = n09_payload.get('test_items', n09_payload.get('dvpr_items', []))
dv_tests = [t for t in test_items if t.get('test_type', '').upper() in ('DV', 'DESIGN VALIDATION')]
pv_tests = [t for t in test_items if t.get('test_type', '').upper() in ('PV', 'PROCESS VALIDATION')]

# Project timeline
milestones = n14_payload.get('milestones', [])
timeline_months = n14_payload.get('timeline_months', 0)
sop_date = n14_payload.get('sop_date', '')

# Tooling from n08 (if available)
n08_payload = n08['payload'] if n08 and n08['status'] in ('ready', 'done') else {}
tooling_from_n08 = n08_payload.get('total_investment_eur', 0)

log.info(f"DV tests: {len(dv_tests)}, PV tests: {len(pv_tests)}")
log.info(f"Timeline: {timeline_months} months, SOP: {sop_date or 'unknown'}")
log.info(f"Tooling from n08: {tooling_from_n08} EUR")
```

---

### Step 2: Build cost items list

```python
log.step("Step 2: Aggregate EDD cost items by category")
```

Build a structured list of non-recurring engineering cost items. Each item belongs to one of these categories:

| Category | Source | Description |
|----------|--------|-------------|
| `tooling` | n08 operations | Molds, dies, forming tools |
| `fixtures` | n08 operations | Assembly fixtures, test fixtures, gauges |
| `DV_testing` | n09 DVPR (DV items) | Design validation test costs |
| `PV_testing` | n09 DVPR (PV items) | Process validation test costs |
| `prototypes` | n14 timeline + n08 process | Prototype parts for DV/PV, customer samples |
| `qualification` | n09 + n14 | PPAP documentation, IMDS, initial sample inspection |
| `project_management` | n14 timeline | Engineering hours over project duration |

```python
cost_items = []
gaps = []
assumptions = []

# ── Tooling ──────────────────────────────────────────────────────────────────
tooling_cost = tooling_from_n08
tooling_confidence = 'S3'
if tooling_cost > 0:
    cost_items.append({
        'category': 'tooling',
        'description': 'Production tooling (molds, dies, forming tools) from process route',
        'estimated_cost_eur': tooling_cost,
        'confidence': tooling_confidence,
        'phase': 'Phase 3 — Process Design',
        'source': 'n08'
    })
else:
    # Tooling cost unknown — flag as assumption
    tooling_cost = 0
    cost_items.append({
        'category': 'tooling',
        'description': 'Production tooling — cost not yet estimated',
        'estimated_cost_eur': 0,
        'confidence': 'S5',
        'phase': 'Phase 3 — Process Design',
        'source': 'estimate'
    })
    assumptions.append({
        'id': 'A-15-tooling',
        'field': 'tooling_cost',
        'value': '0',
        'unit': 'EUR',
        'confidence': 'S5',
        'rationale': 'n08 tooling investment not available; requires process engineer input'
    })

# ── Fixtures ─────────────────────────────────────────────────────────────────
# Estimate fixtures as 10-20% of tooling cost (S4, industry rule-of-thumb)
fixture_pct = 0.15
fixture_cost = round(tooling_cost * fixture_pct)
fixture_confidence = 'S4'
cost_items.append({
    'category': 'fixtures',
    'description': 'Assembly fixtures, test fixtures, gauges (estimated as 15% of tooling)',
    'estimated_cost_eur': fixture_cost,
    'confidence': fixture_confidence,
    'phase': 'Phase 3 — Process Design',
    'source': 'estimate'
})
assumptions.append({
    'id': 'A-15-fixtures',
    'field': 'fixture_cost',
    'value': str(fixture_cost),
    'unit': 'EUR',
    'confidence': 'S4',
    'rationale': f'Estimated as {fixture_pct*100:.0f}% of tooling cost; confirm with manufacturing engineering'
})

# ── DV Testing ───────────────────────────────────────────────────────────────
dv_total = sum(t.get('estimated_cost_eur', 0) for t in dv_tests)
dv_confidence = 'S3' if dv_total > 0 else 'S5'
cost_items.append({
    'category': 'DV_testing',
    'description': f'Design validation testing ({len(dv_tests)} tests from DVPR)',
    'estimated_cost_eur': dv_total,
    'confidence': dv_confidence,
    'phase': 'Phase 3 — Process Design',
    'source': 'n09'
})

# ── PV Testing ───────────────────────────────────────────────────────────────
pv_total = sum(t.get('estimated_cost_eur', 0) for t in pv_tests)
pv_confidence = 'S3' if pv_total > 0 else 'S5'
cost_items.append({
    'category': 'PV_testing',
    'description': f'Process validation testing ({len(pv_tests)} tests from DVPR)',
    'estimated_cost_eur': pv_total,
    'confidence': pv_confidence,
    'phase': 'Phase 4 — Validation',
    'source': 'n09'
})

# ── Prototypes ───────────────────────────────────────────────────────────────
# Estimate prototype cost based on number of DV+PV samples needed
total_samples = sum(t.get('sample_count', 0) for t in test_items)
# Rule-of-thumb: prototype cost = samples × average unit cost × 3 (prototype premium)
# Without unit cost, use S4 estimate
prototype_cost = 0  # AI must estimate based on project specifics
prototype_confidence = 'S4'
cost_items.append({
    'category': 'prototypes',
    'description': f'Prototype parts for DV/PV ({total_samples} samples estimated)',
    'estimated_cost_eur': prototype_cost,
    'confidence': prototype_confidence,
    'phase': 'Phase 2 — Product Design',
    'source': 'estimate'
})
assumptions.append({
    'id': 'A-15-prototypes',
    'field': 'prototype_cost',
    'value': str(prototype_cost),
    'unit': 'EUR',
    'confidence': 'S4',
    'rationale': 'Prototype cost estimated from sample count; confirm with supplier quotation'
})

# ── Qualification ────────────────────────────────────────────────────────────
# PPAP, IMDS, initial sample — typically 3,000-10,000 EUR (S4, company experience)
qualification_cost = 5000  # S4 midpoint estimate
qualification_confidence = 'S4'
cost_items.append({
    'category': 'qualification',
    'description': 'PPAP documentation, IMDS registration, initial sample inspection',
    'estimated_cost_eur': qualification_cost,
    'confidence': qualification_confidence,
    'phase': 'Phase 4 — Validation',
    'source': 'estimate'
})
assumptions.append({
    'id': 'A-15-qualification',
    'field': 'qualification_cost',
    'value': str(qualification_cost),
    'unit': 'EUR',
    'confidence': 'S4',
    'rationale': 'Industry midpoint (3,000-10,000 EUR); adjust based on OEM PPAP level requirements'
})

# ── Project Management ───────────────────────────────────────────────────────
# Engineering hours × rate × project duration
PM_HOURLY_RATE = 85  # EUR/h, S3 company standard
PM_HOURS_PER_MONTH = 40  # S4 estimate for typical APQP project
pm_months = timeline_months if timeline_months > 0 else 18  # default 18 months
pm_cost = round(PM_HOURLY_RATE * PM_HOURS_PER_MONTH * pm_months)
pm_confidence = 'S4'
cost_items.append({
    'category': 'project_management',
    'description': f'Engineering project management ({pm_months} months × {PM_HOURS_PER_MONTH} h/month × {PM_HOURLY_RATE} EUR/h)',
    'estimated_cost_eur': pm_cost,
    'confidence': pm_confidence,
    'phase': 'Phase 1-5 — Full project',
    'source': 'estimate'
})
assumptions.append({
    'id': 'A-15-pm',
    'field': 'project_management_cost',
    'value': str(pm_cost),
    'unit': 'EUR',
    'confidence': 'S4',
    'rationale': f'{PM_HOURS_PER_MONTH} h/month × {pm_months} months × {PM_HOURLY_RATE} EUR/h; confirm with project controller'
})

# ── Total EDD ────────────────────────────────────────────────────────────────
total_edd_eur = sum(ci['estimated_cost_eur'] for ci in cost_items)
log.info(f"Cost items: {len(cost_items)}")
log.info(f"Total EDD: {total_edd_eur} EUR")
for ci in cost_items:
    log.info(f"  {ci['category']}: {ci['estimated_cost_eur']} EUR ({ci['confidence']})")
```

---

### Step 3: Gap identification

```python
log.step("Step 3: Gap identification")
```

| Gap | Rule | Severity | Condition |
|-----|------|----------|-----------|
| SOP date unknown affects timeline costing | R-15-01 | warning | `sop_date` empty or missing in n14 — project_management cost uses assumed duration |
| Cost item has zero or missing estimate | R-15-02 | warning | Any `cost_item.estimated_cost_eur == 0` — needs engineer input |

```python
# R-15-01: SOP date unknown
if not sop_date:
    gaps.append({
        'rule': 'R-15-01',
        'msg': 'SOP date unknown (not in n14) — project management cost uses assumed timeline',
        'severity': 'warning',
        'assumption': f'Assumed {pm_months} months project duration'
    })

# R-15-02: cost items with zero estimate
for ci in cost_items:
    if ci['estimated_cost_eur'] == 0:
        gaps.append({
            'rule': 'R-15-02',
            'msg': f"{ci['category']}: estimated_cost_eur = 0 — needs engineer input",
            'severity': 'warning'
        })

log.info(f"Gaps: {len([g for g in gaps if g['severity']=='error'])} error, {len([g for g in gaps if g['severity']=='warning'])} warning")
```

---

### Step 4: Confidence floor

```python
log.step("Step 4: Determine confidence floor")

CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
all_confs = [ci['confidence'] for ci in cost_items]
confidence_floor = max(all_confs, key=lambda c: CONFIDENCE_ORDER.get(c, 5)) if all_confs else 'S5'
log.info(f"confidence_floor: {confidence_floor}")
```

---

### Step 5: Write artifact

```python
log.step("Step 5: Write artifact")

artifact = {
    'node': 'n15',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'cost_items': cost_items,
        'total_edd_eur': total_edd_eur,
        'project_duration_months': pm_months,
        'sop_date': sop_date
    }
}
store.write('n15', artifact)
```

### Step 6: Close log

```python
log.done(artifact)
```

### Step 7: Write report

```python
from reporter import NodeReport

# AI fills this based on actual execution — all four subsections are mandatory
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n09-output.json` | DVPR test items with DV/PV cost estimates |
| — | `artifacts/n14-output.json` | Project plan with milestones, SOP date, timeline |
| — | `artifacts/n08-output.json` | Process route with tooling investment (transitive) |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n15')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n15",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S4",
  "gaps": [
    {
      "rule": "R-15-01",
      "msg": "SOP date unknown (not in n14) — project management cost uses assumed timeline",
      "severity": "warning",
      "assumption": "Assumed 18 months project duration"
    }
  ],
  "assumptions": [
    {
      "id": "A-15-fixtures",
      "field": "fixture_cost",
      "value": "37500",
      "unit": "EUR",
      "confidence": "S4",
      "rationale": "Estimated as 15% of tooling cost; confirm with manufacturing engineering"
    }
  ],
  "payload": {
    "cost_items": [
      {
        "category": "tooling",
        "description": "Production tooling (molds, dies, forming tools) from process route",
        "estimated_cost_eur": 250000,
        "confidence": "S3",
        "phase": "Phase 3 — Process Design",
        "source": "n08"
      },
      {
        "category": "DV_testing",
        "description": "Design validation testing (8 tests from DVPR)",
        "estimated_cost_eur": 45000,
        "confidence": "S3",
        "phase": "Phase 3 — Process Design",
        "source": "n09"
      }
    ],
    "total_edd_eur": 395000,
    "project_duration_months": 18,
    "sop_date": "2027-06-01"
  }
}
```

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-15-01 | `sop_date` unknown — project management cost uses assumed duration | warning | Confirm SOP date with customer / project manager |
| R-15-02 | Cost item has `estimated_cost_eur == 0` | warning | Needs engineer input to provide estimate |

---

## Optimize Mode

When the user provides more precise data (replacing S4/S5 assumptions with S1/S2 actuals):

1. Read existing `artifacts/n15-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which cost items are updated (compare new data vs existing assumptions):
   - Supplier tooling quotation received (S4 -> S1): update tooling cost
   - Lab test quotation received (S3 -> S1): update DV/PV testing costs
   - SOP date confirmed (R-15-01 resolved): recalculate project management cost
   - PPAP level confirmed: adjust qualification cost
4. Only update affected cost_items; preserve unchanged entries
5. Recalculate `total_edd_eur` and `confidence_floor`
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 5/6/7)
8. Run Validation

### When to fall back to Build mode

- n09 DVPR restructured (new test items added/removed) -> recalculate DV/PV testing
- n14 project plan fundamentally changed (phases restructured) -> recalculate project management
- New cost categories identified (e.g. customer-required special equipment)
- `confidence_floor` degraded from S1/S2 to S4/S5

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n15-output.json`
2. Run Validation below
3. Summarize: cost items count, total EDD, gaps count (by severity), assumptions count, confidence_floor
4. Check: are all expected categories (tooling, fixtures, DV_testing, PV_testing, prototypes, qualification, project_management) present?
5. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n15')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
cost_items = p.get('cost_items', [])
assert len(cost_items) > 0, "cost_items list is empty — no EDD items"

# 3. Total must equal sum of items
total = p.get('total_edd_eur', 0)
item_sum = sum(ci.get('estimated_cost_eur', 0) for ci in cost_items)
assert abs(total - item_sum) < 1.0, \
    f"total_edd_eur ({total}) != sum of cost_items ({item_sum})"

# 4. Each cost item must have required fields
EXPECTED_CATEGORIES = {'tooling', 'fixtures', 'DV_testing', 'PV_testing', 'prototypes', 'qualification', 'project_management'}
found_categories = set()
for ci in cost_items:
    assert ci.get('category'), f"cost_item missing category: {ci}"
    assert ci.get('description'), f"{ci['category']}: description is empty"
    assert ci.get('estimated_cost_eur') is not None, \
        f"{ci['category']}: estimated_cost_eur is None"
    assert ci.get('estimated_cost_eur') >= 0, \
        f"{ci['category']}: estimated_cost_eur must be >= 0 (got {ci['estimated_cost_eur']})"
    assert ci.get('confidence') in ('S1', 'S2', 'S3', 'S4', 'S5'), \
        f"{ci['category']}: confidence invalid: {ci.get('confidence')}"
    assert ci.get('phase'), f"{ci['category']}: phase is empty"
    found_categories.add(ci['category'])

# 5. Check all expected categories are present
missing_cats = EXPECTED_CATEGORIES - found_categories
if missing_cats:
    print(f"⚠ Missing cost categories: {missing_cats}")

# 6. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

print(f"✓ n15 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Cost items: {len(cost_items)}")
print(f"  Total EDD:  {total} EUR")
print(f"  Categories: {sorted(found_categories)}")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
print(f"  Assumptions: {len(artifact.get('assumptions', []))}")
```
