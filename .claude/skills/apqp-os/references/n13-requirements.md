# NODE-13: Capacity（产能/生产能力）

**Purpose**: Determine if the proposed process can meet annual volume requirements; identify bottleneck operations, shift models, headcount, and additional investment needs.
**Input**: `artifacts/n08-output.json` (operations with tact time, annual_capacity), `artifacts/n10-output.json` (PFD with total steps, floor space)
**Output**: `artifacts/n13-output.json`
**Type**: mixed (AI calculates capacity model from upstream data; production engineer confirms shift assumptions and investment decisions)

---

## Precondition Check

```python
import json, sys, math
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# n13 upstream edges (from network.json):
#   n08 → n13 (normal)  — operations with tact time, equipment, annual_capacity
#   n10 → n13 (normal)  — PFD with total steps, floor space
upstream_ids = ['n08', 'n10']
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

# Also read n01 for annual_volume (transitive dependency)
n01 = store.read('n01')
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 未完成 (status={n01['status'] if n01 else 'missing'})"

log = NodeLogger('<project_path>', 'n13')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
log.info(f"n01: status={store.get_status('n01')}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read input data from n01, n08, n10")

n01_payload = n01['payload']
n08 = store.read('n08')
n10 = store.read('n10')
n08_payload = n08['payload']
n10_payload = n10['payload']
```

1. **Read n01** (`artifacts/n01-output.json`):
   - `payload.annual_volume` — customer-specified or assumed annual demand
   - Check for gap R-01-01 (annual_volume is assumption)

2. **Read n08** (`artifacts/n08-output.json`):
   - `payload.operations` — list of manufacturing operations, each with:
     - `tact_time_s` (seconds per piece)
     - `annual_capacity` (pieces/year at single shift if provided)
     - `equipment_type`, `equipment_investment_eur`
     - `labor_count` (operators per station)
   - `payload.total_investment_eur` — aggregate equipment investment

3. **Read n10** (`artifacts/n10-output.json`):
   - `payload.steps` or `payload.process_steps` — total PFD steps
   - `payload.floor_space_m2` — estimated production area
   - `payload.layout_notes` — any spatial constraints

```python
annual_volume = n01_payload.get('annual_volume')
annual_volume_confidence = 'S1'
n01_gap_rules = [g['rule'] for g in n01.get('gaps', [])]
if 'R-01-01' in n01_gap_rules or annual_volume is None:
    if annual_volume is None:
        annual_volume = 50000
    annual_volume_confidence = 'S4'
    log.warn(f"annual_volume={annual_volume} is assumption (S4)")

operations = n08_payload.get('operations', [])
pfd_steps = n10_payload.get('steps', n10_payload.get('process_steps', []))
floor_space_m2 = n10_payload.get('floor_space_m2', 0)

log.info(f"annual_volume: {annual_volume} (confidence: {annual_volume_confidence})")
log.info(f"n08 operations: {len(operations)}")
log.info(f"n10 PFD steps: {len(pfd_steps)}, floor_space: {floor_space_m2} m²")
```

---

### Step 2: Calculate capacity per operation

```python
log.step("Step 2: Calculate annual capacity per operation")
```

For each operation from n08, compute single-shift annual capacity:

```
WORKING_DAYS_PER_YEAR = 250            # S3, company standard
HOURS_PER_SHIFT = 7.5                   # S3, net productive hours
OEE_DEFAULT = 0.85                      # S3, industry default OEE for established lines
SECONDS_PER_SHIFT = HOURS_PER_SHIFT * 3600  # 27,000 s

annual_capacity_1shift = (SECONDS_PER_SHIFT / tact_time_s) * WORKING_DAYS_PER_YEAR * OEE
```

For each operation:
1. Use `tact_time_s` from n08 — if missing, flag as gap
2. Compute `annual_capacity_1shift` using formula above
3. Compare against `annual_volume` to determine if multiple shifts are needed
4. Identify the operation with the lowest `annual_capacity_1shift` as `bottleneck_op`

```python
WORKING_DAYS = 250
HOURS_PER_SHIFT = 7.5
OEE_DEFAULT = 0.85
SECONDS_PER_SHIFT = HOURS_PER_SHIFT * 3600

op_capacities = []
gaps = []
assumptions = []

for op in operations:
    op_name = op.get('operation_name', op.get('name', ''))
    op_id = op.get('operation_id', op.get('id', ''))
    tact_time = op.get('tact_time_s')

    if tact_time is None or tact_time <= 0:
        gaps.append({
            'rule': 'R-13-02',
            'msg': f'{op_id}: tact_time_s missing or invalid — cannot calculate capacity',
            'severity': 'warning'
        })
        log.warn(f"{op_id}: tact_time_s missing — skipping capacity calc")
        continue

    oee = op.get('oee', OEE_DEFAULT)
    cap_1shift = (SECONDS_PER_SHIFT / tact_time) * WORKING_DAYS * oee
    cap_1shift = int(cap_1shift)
    shifts_needed = math.ceil(annual_volume / cap_1shift) if cap_1shift > 0 else 999
    labor = op.get('labor_count', 1)
    investment = op.get('equipment_investment_eur', 0)

    op_capacities.append({
        'operation_id': op_id,
        'operation_name': op_name,
        'tact_time_s': tact_time,
        'oee': oee,
        'annual_capacity_1shift': cap_1shift,
        'shifts_required': shifts_needed,
        'labor_per_shift': labor,
        'equipment_investment_eur': investment
    })
    log.info(f"{op_id} ({op_name}): tact={tact_time}s, cap_1shift={cap_1shift}, shifts_needed={shifts_needed}")
```

---

### Step 3: Determine bottleneck and overall capacity model

```python
log.step("Step 3: Identify bottleneck and build capacity model")
```

1. **Bottleneck** = operation with the lowest `annual_capacity_1shift`
2. **Shifts required** = maximum `shifts_required` across all operations
3. **Annual capacity at tact** = bottleneck `annual_capacity_1shift` x `shifts_required`
4. **Utilization** = `annual_volume / annual_capacity_at_tact * 100`
5. **Headcount** = sum of `labor_per_shift` across all operations x `shifts_required`
6. **Additional investment** = True if any operation requires new equipment or shifts > company limit (typically 3)

```python
if not op_capacities:
    gaps.append({
        'rule': 'R-13-01',
        'msg': 'No operations with valid tact_time — capacity analysis impossible',
        'severity': 'error'
    })
    bottleneck_op = None
    shifts_required = 0
    annual_capacity_at_tact = 0
    utilization_pct = 0
    headcount_total = 0
    additional_investment = False
else:
    bottleneck = min(op_capacities, key=lambda o: o['annual_capacity_1shift'])
    bottleneck_op = bottleneck['operation_id']
    shifts_required = max(o['shifts_required'] for o in op_capacities)
    annual_capacity_at_tact = bottleneck['annual_capacity_1shift'] * shifts_required
    utilization_pct = round(annual_volume / annual_capacity_at_tact * 100, 1) if annual_capacity_at_tact > 0 else 0
    headcount_total = sum(o['labor_per_shift'] for o in op_capacities) * shifts_required
    additional_investment = shifts_required > 1 or any(o['equipment_investment_eur'] > 0 for o in op_capacities)

    # R-13-01: capacity < demand
    if annual_capacity_at_tact < annual_volume:
        gaps.append({
            'rule': 'R-13-01',
            'msg': f'Capacity ({annual_capacity_at_tact} pcs/yr) < demand ({annual_volume} pcs/yr) even at {shifts_required} shifts — bottleneck: {bottleneck_op}',
            'severity': 'error'
        })

    log.info(f"Bottleneck: {bottleneck_op} ({bottleneck['annual_capacity_1shift']} pcs/yr/shift)")
    log.info(f"Shifts required: {shifts_required}")
    log.info(f"Annual capacity at tact: {annual_capacity_at_tact}")
    log.info(f"Utilization: {utilization_pct}%")
    log.info(f"Headcount total: {headcount_total}")
    log.info(f"Additional investment needed: {additional_investment}")
```

---

### Step 4: Confidence and assumptions

```python
log.step("Step 4: Confidence assessment and assumption tracking")
```

**Confidence rules for capacity analysis:**

| Data source | Confidence |
|-------------|------------|
| Customer-confirmed annual volume + measured cycle times from existing line | S1 |
| Customer volume + engineering-estimated cycle times from similar product | S2 |
| Company standard tact times + S3 OEE defaults | S3 |
| Assumed volume (R-01-01) + estimated tact times | S4 |
| No volume data, no cycle time data | S5 |

```python
# Inherit annual_volume assumption from n01
if annual_volume_confidence != 'S1':
    assumptions.append({
        'id': 'A-13-annual-volume',
        'field': 'annual_volume',
        'value': str(annual_volume),
        'unit': '件/年',
        'confidence': annual_volume_confidence,
        'rationale': 'Inherited from n01 — customer RFQ did not specify annual volume'
    })

# OEE is always an assumption unless measured
assumptions.append({
    'id': 'A-13-oee',
    'field': 'oee',
    'value': str(OEE_DEFAULT),
    'unit': '',
    'confidence': 'S3',
    'rationale': 'Industry default OEE (85%); confirm with production data from similar lines'
})

# Working days assumption
assumptions.append({
    'id': 'A-13-working-days',
    'field': 'working_days_per_year',
    'value': str(WORKING_DAYS),
    'unit': 'days',
    'confidence': 'S3',
    'rationale': 'Company standard 250 working days/year'
})

# Determine confidence_floor
CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
all_confs = [annual_volume_confidence, 'S3']  # S3 baseline from OEE/working days
for op in op_capacities:
    # If tact_time came from n08 which is mixed (S3 at best without measurement)
    all_confs.append('S3')
confidence_floor = max(all_confs, key=lambda c: CONFIDENCE_ORDER.get(c, 5))
```

---

### Step 5: Write artifact

```python
log.step("Step 5: Write artifact")

artifact = {
    'node': 'n13',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'annual_demand': annual_volume,
        'annual_demand_confidence': annual_volume_confidence,
        'annual_capacity_at_tact': annual_capacity_at_tact,
        'utilization_pct': utilization_pct,
        'bottleneck_op': bottleneck_op,
        'shifts_required': shifts_required,
        'additional_investment_needed': additional_investment,
        'headcount_total': headcount_total,
        'floor_space_m2': floor_space_m2,
        'working_days_per_year': WORKING_DAYS,
        'hours_per_shift': HOURS_PER_SHIFT,
        'oee_default': OEE_DEFAULT,
        'operation_capacities': op_capacities
    }
}
store.write('n13', artifact)
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
| — | `artifacts/n01-output.json` | annual_volume, gap R-01-01 status |
| — | `artifacts/n08-output.json` | operations with tact_time, equipment, labor |
| — | `artifacts/n10-output.json` | PFD steps, floor_space_m2 |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n13')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n13",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S3",
  "gaps": [
    {
      "rule": "R-13-01",
      "msg": "Capacity (500000 pcs/yr) < demand (600000 pcs/yr) even at 3 shifts — bottleneck: OP-030",
      "severity": "error"
    }
  ],
  "assumptions": [
    {
      "id": "A-13-oee",
      "field": "oee",
      "value": "0.85",
      "unit": "",
      "confidence": "S3",
      "rationale": "Industry default OEE (85%); confirm with production data from similar lines"
    }
  ],
  "payload": {
    "annual_demand": 50000,
    "annual_demand_confidence": "S4",
    "annual_capacity_at_tact": 57375,
    "utilization_pct": 87.2,
    "bottleneck_op": "OP-030",
    "shifts_required": 1,
    "additional_investment_needed": true,
    "headcount_total": 5,
    "floor_space_m2": 120,
    "working_days_per_year": 250,
    "hours_per_shift": 7.5,
    "oee_default": 0.85,
    "operation_capacities": [
      {
        "operation_id": "OP-010",
        "operation_name": "Extrusion",
        "tact_time_s": 15,
        "oee": 0.85,
        "annual_capacity_1shift": 382500,
        "shifts_required": 1,
        "labor_per_shift": 1,
        "equipment_investment_eur": 250000
      }
    ]
  }
}
```

---

## Calculation Reference

### Capacity formula

```
annual_capacity_1shift = (seconds_per_shift / tact_time_s) × working_days × OEE
seconds_per_shift = hours_per_shift × 3600 = 7.5 × 3600 = 27,000 s
```

### Shift model

| Shifts | Available hours/year | Typical use case |
|--------|---------------------|-----------------|
| 1 | 1,875 h | Low volume, new product launch |
| 2 | 3,750 h | Medium volume, standard production |
| 3 | 5,625 h | High volume, mass production |

If `shifts_required > 3`, capacity cannot meet demand with current equipment — flag R-13-01 error.

### Utilization

```
utilization_pct = annual_demand / (bottleneck_capacity_1shift × shifts) × 100
```

Target range: 70-90%. Below 70% indicates overcapacity (cost concern). Above 90% indicates risk of delivery delays.

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-13-01 | `annual_capacity_at_tact < annual_demand` — capacity cannot meet demand | error | Must resolve: add shifts, parallel equipment, or reduce tact time |
| R-13-02 | Operation missing `tact_time_s` — cannot calculate capacity | warning | Per-operation; request data from process engineering |

---

## Optimize Mode

When the user provides more precise data (replacing S3/S4 assumptions with S1/S2 measured values):

1. Read existing `artifacts/n13-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which fields are updated (compare new data vs existing assumptions):
   - Updated `annual_volume` from customer (S4 -> S1): recalculate all capacity ratios
   - Updated `tact_time_s` from time study (S3 -> S1): recalculate affected operation capacities
   - Updated OEE from production data (S3 -> S1): recalculate all capacities
   - Updated shift model from production planning: adjust headcount and utilization
4. Only update affected operation_capacities; preserve unchanged entries
5. Recalculate `confidence_floor` (may improve from S4 to S1/S2)
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 5/6/7)
8. Run Validation

### When to fall back to Build mode

- n08 operations added or removed (process route changed) -> full recalculation needed
- n10 PFD restructured (new steps, different layout) -> full recalculation needed
- Product design change affecting multiple operations simultaneously
- `confidence_floor` degraded from S1/S2 to S4/S5 (data quality regression)

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n13-output.json`
2. Run Validation below
3. Summarize: gaps count (by severity), assumptions count, confidence_floor
4. Check: utilization within target range (70-90%)?
5. Check: all n08 operations represented in operation_capacities?
6. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n13')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
assert p.get('annual_demand', 0) > 0, "annual_demand must be positive"
assert p.get('annual_capacity_at_tact', 0) >= 0, "annual_capacity_at_tact must be non-negative"
assert 0 <= p.get('utilization_pct', 0) <= 200, "utilization_pct out of range (0-200%)"
assert p.get('shifts_required', 0) >= 0, "shifts_required must be non-negative"
assert p.get('headcount_total', 0) >= 0, "headcount_total must be non-negative"
assert p.get('floor_space_m2', 0) >= 0, "floor_space_m2 must be non-negative"

# 3. Operation capacities validation
op_caps = p.get('operation_capacities', [])
for oc in op_caps:
    assert oc.get('operation_id'), f"operation missing operation_id: {oc}"
    assert oc.get('tact_time_s', 0) > 0, \
        f"{oc.get('operation_id')}: tact_time_s must be positive"
    assert oc.get('annual_capacity_1shift', 0) > 0, \
        f"{oc.get('operation_id')}: annual_capacity_1shift must be positive"
    assert oc.get('shifts_required', 0) >= 1, \
        f"{oc.get('operation_id')}: shifts_required must be >= 1"

# 4. Bottleneck consistency: bottleneck_op should match the operation with lowest capacity
if op_caps:
    actual_bottleneck = min(op_caps, key=lambda o: o['annual_capacity_1shift'])
    assert p.get('bottleneck_op') == actual_bottleneck['operation_id'], \
        f"bottleneck_op mismatch: payload says {p.get('bottleneck_op')}, actual is {actual_bottleneck['operation_id']}"

# 5. Cross-check with n08: all operations should be represented
n08 = store.read('n08')
if n08:
    n08_ops = n08.get('payload', {}).get('operations', [])
    n08_ids = {op.get('operation_id', op.get('id', '')) for op in n08_ops}
    n13_ids = {oc['operation_id'] for oc in op_caps}
    missing = n08_ids - n13_ids
    if missing:
        print(f"⚠ n08 operations not in n13 capacity analysis: {missing}")

# 6. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

print(f"✓ n13 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Annual demand:    {p['annual_demand']}")
print(f"  Capacity at tact: {p['annual_capacity_at_tact']}")
print(f"  Utilization:      {p['utilization_pct']}%")
print(f"  Bottleneck:       {p['bottleneck_op']}")
print(f"  Shifts required:  {p['shifts_required']}")
print(f"  Headcount:        {p['headcount_total']}")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
