# NODE-10: PFD（Process Flow Diagram）

**Purpose**: Generate a structured process flow from n08 operations, linking each step to BOM items and control characteristics.
**Input**: `artifacts/n08-output.json` (operations — primary), `artifacts/n04-output.json` (BOM — secondary)
**Output**: `artifacts/n10-output.json`
**Type**: mixed (AI generates PFD from operations; process engineer reviews linkages and floor space)

---

## Precondition Check

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger
from reporter import NodeReport

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# ── Upstream dependencies (from network.json) ────────────────────────────────
# n08 → n10 (normal): operations list with equipment, cycle times, DFMEA refs
# n04 → n10 (secondary): BOM with material items and make/buy classification
upstream_ids = ['n08', 'n04']
error_gaps_total = 0

n08 = store.read('n08')
n04 = store.read('n04')

assert n08 and n08['status'] in ('ready', 'done'), \
    f"n08 未完成 (status={n08['status'] if n08 else 'missing'}) — process route required"
assert n04 and n04['status'] in ('ready', 'done'), \
    f"n04 未完成 (status={n04['status'] if n04 else 'missing'}) — BOM required"

for uid, art in [('n08', n08), ('n04', n04)]:
    error_gaps = [g for g in art.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} has {len(error_gaps)} error gap(s)")

if error_gaps_total:
    print(f"⚠ Upstream total {error_gaps_total} error gap(s) — n10 results may be unreliable")

# Start logger
log = NodeLogger('<project_path>', 'n10')
log.step("Precondition: n08 and n04 artifacts verified")
log.info(f"n08 confidence_floor: {n08['confidence_floor']}")
log.info(f"n04 confidence_floor: {n04['confidence_floor']}")
log.info(f"n08 gaps: {[g['rule'] for g in n08.get('gaps', [])]}")
log.info(f"n04 gaps: {[g['rule'] for g in n04.get('gaps', [])]}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input fields from n08 and n04

```python
log.step("Step 1: Read input fields from n08 and n04")

n08_payload = n08['payload']
n04_payload = n04['payload']

# ── From n08: operations ─────────────────────────────────────────────────────
operations = n08_payload.get('operations', [])
bottleneck_op = n08_payload.get('bottleneck_op')
tact_time_sec = n08_payload.get('tact_time_sec')
total_operators_n08 = n08_payload.get('total_operators')

# ── From n04: BOM items ──────────────────────────────────────────────────────
bom_items = n04_payload.get('bom', [])
# Build a lookup: component_id → BOM item (for material/part number linkage)
bom_lookup = {}
for item in bom_items:
    bom_lookup[item.get('id', '')] = item
    # Also index by component_ref if present
    if item.get('component_ref'):
        bom_lookup[item['component_ref']] = item

log.info(f"n08 operations         : {len(operations)}")
log.info(f"n08 bottleneck         : {bottleneck_op} @ {tact_time_sec}s")
log.info(f"n04 BOM items          : {len(bom_items)}")
```

---

### Step 2: Build process steps from operations

> **PSEUDOCODE** — AI executes inline; do not run this block directly.

```python
log.step("Step 2: Build process steps from n08 operations")

# For EACH operation in n08, create exactly one PFD process step.
# Every n08 operation MUST appear in the PFD — gap R-10-01 fires if any is missing.
#
# For each operation, build a process step with:
#
#   step_id:          Sequential, e.g., "PFD-010", "PFD-020", ...
#                     (increment by 10, matching n08 OP numbering convention)
#
#   step_name:        Descriptive name, derived from operation name.
#                     e.g., "Tube Extrusion" → "Extrude PA12 tube to length"
#
#   operation_ref:    The n08 operation op_id (e.g., "OP10").
#                     This is the traceability link back to the process route.
#
#   input_materials:  List of BOM items consumed or entering at this step.
#                     Look up operation['component_refs'] in bom_lookup.
#                     Each entry: {"bom_id": "...", "part_name": "...", "material": "..."}
#                     For assembly steps, list all sub-components being joined.
#                     For final operations (component_refs=["ALL"]), list finished sub-assemblies.
#
#   output:           What leaves this step. Typically:
#                     - Intermediate: "Extruded tube (cut to length)"
#                     - Sub-assembly: "Feed line sub-assembly"
#                     - Final: "Finished assembly (tested & packaged)"
#
#   equipment:        From operation['equipment_type'].
#                     Keep the generic class; add specifics if known.
#
#   key_parameters:   From operation['key_parameters'].
#                     These are the critical process parameters that must be controlled.
#
#   control_method:   Derived from DFMEA current_control fields.
#                     For each operation['dfmea_refs'], look up the failure mode in n07
#                     and extract current_control_detection / current_control_prevention.
#                     If no DFMEA ref, use generic: "Operator visual check" or
#                     "Per work instruction".
#                     If SC/CC item linked to this step (see Step 3), the control
#                     method MUST be specific (not just "visual check").
#
#   sc_cc_refs:       List of SC/CC references linked to this step.
#                     Populated in Step 3.
#
#   operator_count:   From operation['operators'].

process_steps = []
_step_seq = 0

# AI iterates operations and builds process_steps here.
# Each operation produces exactly one process step.

log.info(f"Process steps built: {len(process_steps)}")
```

---

### Step 3: Link SC/CC characteristics to process steps

> **PSEUDOCODE** — AI executes inline; do not run this block directly.

```python
log.step("Step 3: Link SC/CC characteristics to process steps")

# SC/CC items come from multiple sources:
#   - n04 BOM: items with sc_cc_ref field
#   - n08 operations: dfmea_refs linking to n07 failure modes with sc_cc type
#   - n07 DFMEA: failure modes flagged as SC or CC
#
# For each SC/CC item:
#   1. Identify which process step(s) control this characteristic.
#      Match by: component_ref overlap between the SC/CC source and the step's
#      operation_ref → operation['component_refs'].
#   2. Append the SC/CC reference to the step's sc_cc_refs list.
#   3. Verify the step has a specific control_method (not generic).
#      If control_method is missing or generic → flag gap R-10-02.
#
# Track coverage:
#   - sc_cc_covered: items linked to at least one step with specific control
#   - sc_cc_uncovered: items without specific control method → R-10-02 warning

sc_cc_covered = []
sc_cc_uncovered = []

# AI iterates SC/CC items and links them to process steps here.

log.info(f"SC/CC items linked    : {len(sc_cc_covered)}")
if sc_cc_uncovered:
    log.info(f"SC/CC without control : {len(sc_cc_uncovered)} → R-10-02 gaps")
```

---

### Step 4: Compute process summary

```python
log.step("Step 4: Compute process summary")

total_steps = len(process_steps)
total_operators = sum(step.get('operator_count', 0) for step in process_steps)

# ── Estimated floor space ────────────────────────────────────────────────────
# AI estimates floor space based on equipment types and step count.
# Rule of thumb (industry baseline, S4 confidence):
#   - Primary forming equipment (extruder, press, mold): 20-50 m² each
#   - Assembly/test station: 8-15 m² each
#   - Material handling / aisle: 30% overhead on sum of station areas
#
# The AI should estimate per-step area, sum them, then add 30% overhead.
# Record the estimate as an assumption.

station_areas = []
for step in process_steps:
    # AI estimates area per step based on equipment type
    # Heavy equipment: 30-50 m²; light station: 8-15 m²; test bench: 10-20 m²
    pass

raw_area = sum(station_areas)
estimated_floor_space_m2 = round(raw_area * 1.3)  # +30% for aisles/handling

process_summary = {
    "total_steps": total_steps,
    "total_operators": total_operators,
    "estimated_floor_space_m2": estimated_floor_space_m2,
}

log.info(f"Total steps            : {total_steps}")
log.info(f"Total operators        : {total_operators}")
log.info(f"Estimated floor space  : {estimated_floor_space_m2} m²")
```

---

### Step 5: Gap identification

```python
log.step("Step 5: Gap identification")

gaps = []

# ── R-10-01: n08 operation not mapped to PFD step (ERROR) ────────────────────
# Every n08 operation MUST have a corresponding PFD step.
mapped_op_refs = set(step['operation_ref'] for step in process_steps)
all_op_ids = set(op['op_id'] for op in operations)

unmapped_ops = all_op_ids - mapped_op_refs
for op_id in unmapped_ops:
    msg = f"n08 operation {op_id} has no corresponding PFD step — every operation must be mapped"
    log.gap("R-10-01", msg, "error")
    gaps.append({"rule": "R-10-01", "msg": msg, "severity": "error", "assumption": None})

# ── R-10-02: SC/CC item without control method (WARNING) ─────────────────────
# Every SC/CC item linked to a process step must have a specific control method.
for item in sc_cc_uncovered:
    msg = (f"SC/CC item {item.get('ref', item.get('id', '?'))} linked to process step "
           f"but no specific control method defined — add detection/prevention control")
    log.gap("R-10-02", msg, "warning")
    gaps.append({"rule": "R-10-02", "msg": msg, "severity": "warning",
                 "assumption": "Control method to be confirmed by process engineer"})

log.info(f"Gaps identified: {len(gaps)} ({sum(1 for g in gaps if g['severity']=='error')} error, "
         f"{sum(1 for g in gaps if g['severity']=='warning')} warning)")
```

---

### Step 6: Write artifact

```python
log.step("Step 6: Write artifact")

# ── Confidence floor ──────────────────────────────────────────────────────────
# Determined by the lowest confidence across:
#   - Upstream n08 confidence_floor (inherited)
#   - Floor space estimate (typically S4)
#   - Control method completeness
# n10 confidence_floor is at least as low as n08's.
conf_candidates = [n08['confidence_floor']]
# If floor space is estimated → S4
conf_candidates.append('S4')  # floor space estimate is always S4 unless measured
# If any SC/CC item lacks control → stays at current floor
valid_confs = [c for c in conf_candidates if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S4'

# ── Build assumptions ────────────────────────────────────────────────────────
assumptions = []
# Floor space assumption (always present unless measured)
assumptions.append({
    "id": "A-01",
    "field": "estimated_floor_space_m2",
    "value": str(estimated_floor_space_m2),
    "unit": "m²",
    "confidence": "S4",
    "rationale": "Estimated from equipment types with 30% aisle overhead — industry baseline"
})
# Add any other assumptions generated during Step 2-4

# ── Build artifact ────────────────────────────────────────────────────────────
artifact = {
    "node":             "n10",
    "project":          n08.get("project"),
    "status":           "ready",
    "produced_at":      datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":             gaps,
    "assumptions":      assumptions,
    "payload": {
        "process_steps":    process_steps,
        "process_summary":  process_summary,
    }
}

store.write('n10', artifact)
```

---

### Step 7: Close log

```python
log.done(artifact)
```

---

### Step 8: Write report

```python
# AI fills in actual values from this execution run.
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| 上游 | `artifacts/n08-output.json` | Process route — operations, equipment, cycle times, DFMEA refs |
| 上游 | `artifacts/n04-output.json` | BOM — material items, component references |

### 过程中解决的问题

- (AI fills: e.g., "Operation OP50 component_refs=['ALL'] — resolved to all make components for final assembly step")
- (AI fills: or "无异常" if none)

### 假设与判断

- **estimated_floor_space_m2**: Estimated from equipment types with 30% aisle overhead (S4)
- (AI fills: any additional assumptions about control methods, material flow, etc.)

### 对 skill 的改进

- (AI fills: e.g., "Added control method mapping from DFMEA current_control fields")
- (AI fills: or "无" if none)
"""

report = NodeReport('<project_path>', 'n10')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Payload Schema

Each process step in `payload.process_steps` must conform to:

```json
{
  "step_id": "PFD-010",
  "step_name": "Extrude PA12 tube to length",
  "operation_ref": "OP10",
  "input_materials": [
    {"bom_id": "BOM-001", "part_name": "PA12 resin", "material": "PA12 GF30"}
  ],
  "output": "Extruded tube (cut to length)",
  "equipment": "Single-screw extruder",
  "key_parameters": ["melt temp 220±5°C", "line speed 15 m/min"],
  "control_method": "SPC on melt temperature; visual check per WI-EXT-001",
  "sc_cc_refs": ["SC-001"],
  "operator_count": 1
}
```

Top-level payload fields:

| Field | Type | Description |
|-------|------|-------------|
| `process_steps` | list | Ordered list of all PFD steps (one per n08 operation) |
| `process_summary` | object | Aggregated metrics for the entire process flow |

`process_summary` fields:

| Field | Type | Description |
|-------|------|-------------|
| `total_steps` | int | Number of process steps in the PFD |
| `total_operators` | int | Sum of operator_count across all steps |
| `estimated_floor_space_m2` | number | Estimated total production floor area including aisles |

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-10-01 | n08 operation not mapped to any PFD step | error | Create PFD step for the unmapped operation |
| R-10-02 | SC/CC item linked to a step but no specific control method defined | warning | Define detection or prevention control for the characteristic |

---

## Downstream Impact

n10 feeds into capacity analysis. Its quality directly impacts:

| Downstream | Edge Type | What It Consumes |
|------------|-----------|-------------------|
| **n13** (Capacity) | normal | Process steps, operator counts, floor space → capacity planning and investment |

Errors in step count, operator allocation, or floor space estimates affect n13 → n17 (NRC) → n18 (Quotation).

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n10')
p = a.get('payload', {})

# 1. Status and confidence
assert a['status'] in ('ready', 'done', 'waiting_human'), f"status invalid: {a['status']}"
assert a.get('confidence_floor'), "confidence_floor not set"

# 2. Process steps non-empty
steps = p.get('process_steps', [])
assert len(steps) > 0, "process_steps list is empty — no PFD generated"

# 3. Every step has required fields
required_step_fields = ['step_id', 'step_name', 'operation_ref', 'input_materials',
                        'output', 'equipment', 'key_parameters', 'control_method',
                        'sc_cc_refs', 'operator_count']
for step in steps:
    for field in required_step_fields:
        assert field in step, f"Step {step.get('step_id', '?')} missing '{field}'"

# 4. Every n08 operation is mapped (R-10-01)
n08 = store.read('n08')
n08_op_ids = set(op['op_id'] for op in n08['payload'].get('operations', []))
pfd_op_refs = set(step['operation_ref'] for step in steps)
unmapped = n08_op_ids - pfd_op_refs
gap_rules = [g['rule'] for g in a.get('gaps', [])]
assert not unmapped or 'R-10-01' in gap_rules, \
    f"n08 operations {unmapped} not mapped to PFD and R-10-01 not flagged"

# 5. Process summary present and valid
summary = p.get('process_summary', {})
assert summary.get('total_steps', 0) > 0, "process_summary.total_steps must be > 0"
assert summary.get('total_operators', 0) > 0, "process_summary.total_operators must be > 0"
assert summary.get('estimated_floor_space_m2', 0) > 0, \
    "process_summary.estimated_floor_space_m2 must be > 0"
assert summary['total_steps'] == len(steps), \
    f"total_steps ({summary['total_steps']}) != actual step count ({len(steps)})"

# 6. Operator count consistency
sum_operators = sum(step.get('operator_count', 0) for step in steps)
assert sum_operators == summary['total_operators'], \
    f"Sum of step operator_count ({sum_operators}) != total_operators ({summary['total_operators']})"

# 7. Numeric sanity per step
for step in steps:
    assert step['operator_count'] >= 0, f"{step['step_id']} operator_count must be >= 0"
    assert step.get('operation_ref'), f"{step['step_id']} must reference an n08 operation"

# 8. Gaps completeness
for g in a.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"Gap format incomplete: {g}"

print(f"✓ n10 validation passed — confidence_floor: {a['confidence_floor']}")
print(f"  Process steps         : {len(steps)}")
print(f"  Total operators       : {summary['total_operators']}")
print(f"  Floor space (m²)      : {summary['estimated_floor_space_m2']}")
print(f"  SC/CC refs in PFD     : {sum(len(s.get('sc_cc_refs', [])) for s in steps)}")
print(f"  Gaps                  : {gap_rules}")
```

---

## Optimize Mode

When the process engineer provides confirmed data (replacing AI estimates with actual values):

1. Read existing `artifacts/n10-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which fields are being updated (compare new data vs existing assumptions):
   - Confirmed floor space measurements (S4 → S1/S2)
   - Confirmed control methods from quality planning
   - Updated input materials after BOM revision
   - Confirmed operator assignments from production planning
4. Update only affected process steps; preserve unchanged steps
5. Recalculate `process_summary` (totals may change)
6. Recalculate `confidence_floor`
7. Remove resolved assumptions and gaps; update artifact
8. Write artifact → close log → write report
9. Run Validation

### When to fall back to Build mode

- **Process steps added or removed** (n08 operations changed)
- **Upstream n08 payload structure changed** (new operations or operation types)
- **Upstream n04 BOM structure changed** (new materials or components)
- **confidence_floor degraded** from S1/S2 to S4/S5 (data quality regression)

If uncertain, choose Build — full rebuild is safer than incomplete update.

**Key**: After Optimize, run `orchestrator.py affected n10` — typically impacts n13 (Capacity), and indirectly n17 (NRC) → n18 (Quotation).

---

## Review Mode

Read-only quality check — no files modified:

1. Read `artifacts/n10-output.json`
2. Run Validation code above
3. Output quality summary:
   - Step count, total operators, floor space estimate
   - Coverage: n08 operations mapped/unmapped
   - SC/CC linkage: items with/without specific control methods
   - confidence_floor, gaps list
4. Do not write artifact
