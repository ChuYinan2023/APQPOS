# NODE-08: Process Route（工艺路线）

**Purpose**: Define manufacturing operations for each "make" item in the component tree, with equipment type, cycle time, labor, and investment estimates.
**Input**: `artifacts/n03-output.json` (components), `artifacts/n07-output.json` (DFMEA — high RPN items influence process controls)
**Output**: `artifacts/n08-output.json`
**Type**: mixed (AI proposes process route from component types; process engineer confirms)

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

# ── Upstream dependencies (from network.json) ────────────────────────────────
# n03 → n08 (normal): component tree with make/buy classification
# n07 → n08 (secondary): DFMEA failure modes for process control integration
upstream_ids = ['n03', 'n07']
error_gaps_total = 0

n03 = store.read('n03')
n07 = store.read('n07')

assert n03 and n03['status'] in ('ready', 'done'), \
    f"n03 未完成 (status={n03['status'] if n03 else 'missing'}) — component tree required"
assert n07 and n07['status'] in ('ready', 'done'), \
    f"n07 未完成 (status={n07['status'] if n07 else 'missing'}) — DFMEA required"

for uid, art in [('n03', n03), ('n07', n07)]:
    error_gaps = [g for g in art.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} has {len(error_gaps)} error gap(s)")

if error_gaps_total:
    print(f"⚠ Upstream total {error_gaps_total} error gap(s) — n08 results may be unreliable")

# Start logger
log = NodeLogger('<project_path>', 'n08')
log.step("Precondition: n03 and n07 artifacts verified")
log.info(f"n03 confidence_floor: {n03['confidence_floor']}")
log.info(f"n07 confidence_floor: {n07['confidence_floor']}")
log.info(f"n03 gaps: {[g['rule'] for g in n03.get('gaps', [])]}")
log.info(f"n07 gaps: {[g['rule'] for g in n07.get('gaps', [])]}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input fields

```python
log.step("Step 1: Read input fields from n03 and n07")

n03_payload = n03['payload']
n07_payload = n07['payload']

# ── From n03: component tree ─────────────────────────────────────────────────
components = n03_payload.get('components', [])

# Identify "make" components — components that require manufacturing operations.
# Convention: components where type suggests in-house manufacturing.
# Typical make types: tube, end_form, damper, stamped_metal, injection_molded,
#   machined, assembled_sub, bracket, housing, etc.
# Typical buy types: quick_connector, seal, fastener, clip, sensor, etc.
#
# Decision rule: use component 'make_buy' field if present (from n04 BOM);
# otherwise infer from type — buy types are standardized purchased parts.
BUY_TYPES = {'quick_connector', 'seal', 'fastener', 'clip', 'sensor',
             'o_ring', 'gasket', 'standard_part'}

make_components = []
for comp in components:
    mb = comp.get('make_buy', '').lower()
    if mb == 'buy':
        continue
    if mb == 'make' or comp.get('type', '').lower() not in BUY_TYPES:
        make_components.append(comp)

# ── From n07: DFMEA failure modes ────────────────────────────────────────────
failure_modes = n07_payload.get('failure_modes', [])

# High-RPN failure modes: RPN > 100 OR severity >= 9
high_rpn_fms = []
for fm in failure_modes:
    rpn = fm.get('rpn', 0)
    severity = fm.get('severity', 0)
    if rpn > 100 or severity >= 9:
        high_rpn_fms.append(fm)

log.info(f"Total components from n03   : {len(components)}")
log.info(f"Make components (need route) : {len(make_components)}")
log.info(f"Buy components (skip)        : {len(components) - len(make_components)}")
log.info(f"DFMEA failure modes (total)  : {len(failure_modes)}")
log.info(f"DFMEA high-RPN (>100 or S≥9) : {len(high_rpn_fms)}")
```

---

### Step 2: Select process template per component type

> **PSEUDOCODE** — AI executes inline; do not run this block directly.

```python
log.step("Step 2: Select process template and build operations per make component")

# ── Process template library ──────────────────────────────────────────────────
# Each template defines the standard sequence of operations for a component type.
# AI selects the matching template based on component type, then instantiates
# operations with project-specific parameters.
#
# IMPORTANT: These templates are GENERIC. The AI must adapt parameters
# (cycle times, equipment, key_parameters) to the actual component dimensions
# and material from n03. Values below are starting-point defaults.
#
# ┌──────────────────────┬──────────────────────────────────────────────────────┐
# │ Component Type       │ Default Operation Sequence                          │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ tube / pipe          │ OP10 Extrusion → OP20 Cut-to-length →              │
# │                      │ OP30 Bend → OP40 End-form → OP50 Assembly →        │
# │                      │ OP60 Leak/pressure test                             │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ injection_molded     │ OP10 Injection mold → OP20 Trim/deflash →          │
# │                      │ OP30 Visual inspect                                 │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ stamped_metal        │ OP10 Blank → OP20 Stamp/form → OP30 Deburr →      │
# │                      │ OP40 Surface treatment (plate/coat) →               │
# │                      │ OP50 Dimensional inspect                            │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ machined             │ OP10 Rough machine → OP20 Finish machine →         │
# │                      │ OP30 Dimensional inspect                            │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ end_form             │ OP10 End-forming (swage/flare/bead) →              │
# │                      │ OP20 Dimensional inspect                            │
# │                      │ (Often integrated into parent tube route)            │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ damper               │ OP10 Sub-assembly → OP20 Weld/braze →              │
# │                      │ OP30 Leak test → OP40 Dimensional inspect           │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ assembled_sub        │ OP10 Sub-component assembly → OP20 Functional test →│
# │                      │ OP30 Visual inspect                                 │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ bracket / housing    │ OP10 Stamp/cast → OP20 Machine (if needed) →       │
# │                      │ OP30 Surface treatment → OP40 Dimensional inspect   │
# ├──────────────────────┼──────────────────────────────────────────────────────┤
# │ (fallback/unknown)   │ OP10 Primary process → OP20 Secondary process →    │
# │                      │ OP30 Inspection                                     │
# └──────────────────────┴──────────────────────────────────────────────────────┘
#
# For each make component:
#   1. Match component['type'] to template above (case-insensitive).
#   2. Instantiate each operation with:
#      - op_id: "OP{seq}" where seq increments by 10 (OP10, OP20, ...)
#      - name: operation name from template
#      - component_refs: [comp['id']] (may reference multiple components if shared)
#      - equipment_type: generic equipment class (AI selects based on dimensions/material)
#      - cycle_time_sec: AI estimate based on component size/complexity
#        confidence = S4 if no process data, S3 if industry-typical estimate
#      - operators: typical operator count (usually 1)
#      - investment_eur: AI estimate based on equipment type
#        confidence = S5 if pure AI estimate, S4 if industry-benchmarked
#      - key_parameters: list of critical process parameters (strings)
#        e.g., ["melt temp 220±5°C", "line speed 15 m/min"]
#      - dfmea_refs: [] (populated in Step 3)
#      - is_bottleneck: False (computed in Step 4)
#      - confidence: min confidence of cycle_time and investment estimates
#   3. Append all operations to a flat operations list.
#
# Track assumptions for each estimate (cycle_time, investment, equipment_type).

operations = []
assumptions = []
_op_global_seq = 0  # global OP counter across all components

# AI iterates make_components and builds operations here.
# Each component produces N operations; op_id = f"OP{(_op_global_seq + i) * 10}"
# grouped logically per component.
```

---

### Step 3: DFMEA integration — link failure modes to operations

> **PSEUDOCODE** — AI executes inline; do not run this block directly.

```python
log.step("Step 3: DFMEA integration — link high-RPN failure modes to operations")

# For each high-RPN failure mode from n07:
#
#   1. Identify which operation(s) can detect or prevent this failure:
#      - Match by component_ref: fm['component_ref'] ↔ operation['component_refs']
#      - Match by failure cause: if cause relates to a process step,
#        link to that operation (e.g., "weld porosity" → welding operation)
#      - Match by detection method: if current_control_detection is
#        "100% test" or "functional test" → link to test/inspection operations
#
#   2. For each matched operation, append fm['id'] to operation['dfmea_refs']
#
#   3. If a high-RPN failure mode has NO matching operation:
#      a. If current_control_detection suggests "100% test" →
#         ADD a mandatory test operation to the route
#         (e.g., OP-XX "100% leak test per DFMEA FM-xxx")
#      b. If failure cause relates to process parameter →
#         ADD key_parameter to the relevant operation
#         (e.g., "weld current 180±5A per FM-xxx")
#      c. If no operation can be mapped → flag as gap R-08-02
#
#   4. Track which failure modes are covered vs uncovered.

covered_fm_ids = set()
uncovered_fms = []

# AI iterates high_rpn_fms and links/adds operations here.
# After this step, every operation has its dfmea_refs populated.

log.info(f"High-RPN failure modes covered: {len(covered_fm_ids)}/{len(high_rpn_fms)}")
if uncovered_fms:
    log.info(f"Uncovered failure modes: {[fm['id'] for fm in uncovered_fms]}")
```

---

### Step 4: Add final operations and compute line summary

> **PSEUDOCODE** — AI executes inline; do not run this block directly.

```python
log.step("Step 4: Add final operations and compute line summary")

# ── 4a. Final operations (common to all products) ────────────────────────────
# These are appended AFTER all component-specific operations.
# Include only those relevant to the product (check n01/n03 for requirements):
#
#   - Leak/pressure test: if ANY component has pressure/leak requirements
#     (check n01 special_characteristics or n03 assembly_interfaces for "leak")
#     Equipment: leak test bench / pressure decay tester
#
#   - Dimensional inspection: ALWAYS included
#     Equipment: CMM or vision system
#
#   - Cleanliness check: if n01 mentions cleanliness spec
#     (check n01 payload for cleanliness or particulate requirements)
#     Equipment: gravimetric cleanliness tester
#
#   - Packaging + labeling: ALWAYS included
#     Equipment: packaging station + label printer
#
# Each final operation gets component_refs = ["ALL"] or list of all make comp IDs.
# dfmea_refs populated from Step 3 if applicable.

# ── 4b. Identify bottleneck ──────────────────────────────────────────────────
# bottleneck_op = operation with max cycle_time_sec
# Set is_bottleneck = True on that operation.

# ── 4c. Compute line summary ─────────────────────────────────────────────────
# total_cycle_time_sec = sum of all operation cycle_time_sec
# tact_time_sec        = max(cycle_time_sec) across all operations (bottleneck)
# total_operators      = sum of all operation operators
# total_investment_eur = sum of all operation investment_eur
# annual_capacity_at_tact = floor(available_seconds_per_year / tact_time_sec)
#   where available_seconds_per_year = shifts_per_day * hours_per_shift * 3600 * working_days
#   Default assumption: 2 shifts × 8 h × 3600 × 250 days = 14,400,000 sec/year（中国标准：两班制×8h×250工作日）
#   (This is an assumption — record it.)

bottleneck_op = max(operations, key=lambda op: op['cycle_time_sec'])
bottleneck_op['is_bottleneck'] = True

total_cycle_time_sec = sum(op['cycle_time_sec'] for op in operations)
tact_time_sec = bottleneck_op['cycle_time_sec']
total_operators = sum(op['operators'] for op in operations)
total_investment_eur = sum(op['investment_eur'] for op in operations)

AVAILABLE_SEC_PER_YEAR = 2 * 8.0 * 3600 * 250  # = 14,400,000（两班制×8h×250工作日）
annual_capacity_at_tact = int(AVAILABLE_SEC_PER_YEAR // tact_time_sec) if tact_time_sec > 0 else 0

log.info(f"Total operations        : {len(operations)}")
log.info(f"Total cycle time (sec)  : {total_cycle_time_sec}")
log.info(f"Bottleneck              : {bottleneck_op['op_id']} ({bottleneck_op['name']}) @ {tact_time_sec}s")
log.info(f"Total operators         : {total_operators}")
log.info(f"Total investment (EUR)  : {total_investment_eur}")
log.info(f"Annual capacity at tact : {annual_capacity_at_tact}")
```

---

### Step 5: Gap identification

```python
log.step("Step 5: Gap identification")

gaps = []

# ── R-08-01: make component without process route (ERROR) ────────────────────
# Every make component must have at least one operation referencing it.
comps_with_ops = set()
for op in operations:
    for ref in op.get('component_refs', []):
        comps_with_ops.add(ref)

comps_without_route = [c['id'] for c in make_components if c['id'] not in comps_with_ops]
for comp_id in comps_without_route:
    msg = f"Make component {comp_id} has no process route — every make item must have operations"
    log.gap("R-08-01", msg, "error")
    gaps.append({"rule": "R-08-01", "msg": msg, "severity": "error", "assumption": None})

# ── R-08-02: high-RPN failure mode not covered by any operation (WARNING) ────
for fm in uncovered_fms:
    msg = (f"High-RPN failure mode {fm['id']} (RPN={fm.get('rpn')}, S={fm.get('severity')}) "
           f"not covered by any operation control — add detection/prevention step")
    log.gap("R-08-02", msg, "warning")
    gaps.append({"rule": "R-08-02", "msg": msg, "severity": "warning",
                 "assumption": "Failure mode may require dedicated process step or parameter control"})

# ── R-08-03: no test/inspection operation (WARNING) ─────────────────────────
test_keywords = {'test', 'inspect', 'check', 'measurement', 'cmm', 'vision', 'leak'}
has_test_op = any(
    any(kw in op['name'].lower() for kw in test_keywords)
    for op in operations
)
if not has_test_op:
    msg = "No test or inspection operation found in process route — add at least one quality gate"
    log.gap("R-08-03", msg, "warning")
    gaps.append({"rule": "R-08-03", "msg": msg, "severity": "warning",
                 "assumption": "Minimum one inspection operation required per automotive standards"})

log.info(f"Gaps identified: {len(gaps)} ({sum(1 for g in gaps if g['severity']=='error')} error, "
         f"{sum(1 for g in gaps if g['severity']=='warning')} warning)")
```

---

### Step 6: Write artifact

```python
log.step("Step 6: Write artifact")

# ── Confidence floor ──────────────────────────────────────────────────────────
# Determined by the lowest confidence across all operations.
all_confs = [op.get('confidence', 'S3') for op in operations]
valid_confs = [c for c in all_confs if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S4'

# ── Build artifact ────────────────────────────────────────────────────────────
artifact = {
    "node":             "n08",
    "project":          n03.get("project"),
    "status":           "ready",
    "produced_at":      datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":             gaps,
    "assumptions":      assumptions,
    "payload": {
        "process_version":       1,
        "operations":            operations,
        "total_cycle_time_sec":  total_cycle_time_sec,
        "bottleneck_op":         bottleneck_op['op_id'],
        "tact_time_sec":         tact_time_sec,
        "total_operators":       total_operators,
        "total_investment_eur":  total_investment_eur,
        "annual_capacity_at_tact": annual_capacity_at_tact,
    }
}

store.write('n08', artifact)
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
| 上游 | `artifacts/n03-output.json` | Component tree — make/buy items, dimensions |
| 上游 | `artifacts/n07-output.json` | DFMEA failure modes, RPN values |

### 过程中解决的问题

- (AI fills: e.g., "Component COMP-003 type 'damper' not in template — used assembled_sub fallback")
- (AI fills: or "无异常" if none)

### 假设与判断

- (AI fills: each cycle_time / investment / equipment assumption with confidence level)
- Annual capacity assumes 2 shifts × 8h × 250 working days（中国标准）(S4 assumption)

### 对 skill 的改进

- (AI fills: e.g., "Add 'welded' component type to process template library")
- (AI fills: or "无" if none)
"""

report = NodeReport('<project_path>', 'n08')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Payload Schema

Each operation in `payload.operations` must conform to:

```json
{
  "op_id": "OP10",
  "name": "Tube Extrusion",
  "component_refs": ["COMP-01", "COMP-02"],
  "equipment_type": "Single-screw extruder",
  "cycle_time_sec": 30,
  "operators": 1,
  "investment_eur": 120000,
  "key_parameters": ["melt temp 220±5°C", "line speed 15 m/min"],
  "dfmea_refs": ["FM-001"],
  "is_bottleneck": false,
  "confidence": "S3"
}
```

Top-level payload fields:

| Field | Type | Description |
|-------|------|-------------|
| `process_version` | int | Incremented on each Optimize pass |
| `operations` | list | All manufacturing operations (flat list, ordered by execution sequence) |
| `total_cycle_time_sec` | number | Sum of all operation cycle times |
| `bottleneck_op` | string | op_id of the operation with highest cycle_time_sec |
| `tact_time_sec` | number | = bottleneck cycle time (determines line speed) |
| `total_operators` | int | Sum of operators across all operations |
| `total_investment_eur` | number | Sum of investment across all operations |
| `annual_capacity_at_tact` | int | floor(available_sec_per_year / tact_time_sec) |

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-08-01 | Make component has no operations in process route | error | Add operations for this component |
| R-08-02 | High-RPN failure mode (RPN>100 or S≥9) not covered by any operation control | warning | Add detection/prevention operation or parameter |
| R-08-03 | No test/inspection operation in entire route | warning | Add at least one quality gate operation |

---

## Downstream Impact

n08 is the highest fan-out node after n03. Its quality directly impacts:

| Downstream | Edge Type | What It Consumes |
|------------|-----------|-------------------|
| **n10** (PFD) | normal | Operation sequence → process flow diagram |
| **n11** (Material Cost) | secondary | Operation list → process scrap rates, material consumption context |
| **n12** (Conversion Cost) | normal | cycle_time_sec, operators, investment_eur → per-piece conversion cost |
| **n13** (Capacity) | normal | tact_time_sec, annual_capacity_at_tact → capacity analysis |

Errors in cycle time or investment estimates cascade through n12 → n16 (RC) → n18 (Quotation).

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n08')
p = a.get('payload', {})

# 1. Status and confidence
assert a['status'] in ('ready', 'done', 'waiting_human'), f"status invalid: {a['status']}"
assert a.get('confidence_floor'), "confidence_floor not set"

# 2. Operations list non-empty
ops = p.get('operations', [])
assert len(ops) > 0, "operations list is empty — no process route defined"

# 3. Every operation has required fields
required_op_fields = ['op_id', 'name', 'component_refs', 'equipment_type',
                      'cycle_time_sec', 'operators', 'investment_eur',
                      'key_parameters', 'dfmea_refs', 'is_bottleneck', 'confidence']
for op in ops:
    for field in required_op_fields:
        assert field in op, f"Operation {op.get('op_id', '?')} missing '{field}'"

# 4. Every make component has at least one operation (R-08-01)
# Re-derive make components from n03
n03 = store.read('n03')
BUY_TYPES = {'quick_connector', 'seal', 'fastener', 'clip', 'sensor',
             'o_ring', 'gasket', 'standard_part'}
make_comp_ids = set()
for comp in n03['payload'].get('components', []):
    mb = comp.get('make_buy', '').lower()
    if mb == 'buy':
        continue
    if mb == 'make' or comp.get('type', '').lower() not in BUY_TYPES:
        make_comp_ids.add(comp['id'])

covered_comp_ids = set()
for op in ops:
    for ref in op.get('component_refs', []):
        covered_comp_ids.add(ref)

uncovered = make_comp_ids - covered_comp_ids - {'ALL'}
# 'ALL' is allowed as a wildcard for final operations
if 'ALL' in covered_comp_ids:
    uncovered = set()  # ALL covers everything
assert not uncovered, f"Make components without operations: {uncovered}"

# 5. Numeric sanity
assert p.get('total_investment_eur', 0) > 0, "total_investment_eur must be > 0"
assert p.get('total_cycle_time_sec', 0) > 0, "total_cycle_time_sec must be > 0"
assert p.get('tact_time_sec', 0) > 0, "tact_time_sec must be > 0"
assert p.get('total_operators', 0) > 0, "total_operators must be > 0"
assert p.get('annual_capacity_at_tact', 0) > 0, "annual_capacity_at_tact must be > 0"

for op in ops:
    assert op['cycle_time_sec'] > 0, f"{op['op_id']} cycle_time_sec must be > 0"
    assert op['investment_eur'] >= 0, f"{op['op_id']} investment_eur must be >= 0"

# 6. Exactly one bottleneck
bottlenecks = [op for op in ops if op.get('is_bottleneck')]
assert len(bottlenecks) == 1, f"Expected exactly 1 bottleneck, found {len(bottlenecks)}"
assert bottlenecks[0]['op_id'] == p.get('bottleneck_op'), \
    "bottleneck_op does not match the operation flagged is_bottleneck=True"

# 7. Gaps completeness
for g in a.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"Gap format incomplete: {g}"

# 8. At least one test/inspection operation (R-08-03 check)
test_keywords = {'test', 'inspect', 'check', 'measurement', 'cmm', 'vision', 'leak'}
has_test = any(any(kw in op['name'].lower() for kw in test_keywords) for op in ops)
gap_rules = [g['rule'] for g in a.get('gaps', [])]
assert has_test or 'R-08-03' in gap_rules, \
    "No test operation and R-08-03 gap not flagged"

print(f"✓ n08 validation passed — confidence_floor: {a['confidence_floor']}")
print(f"  Operations           : {len(ops)}")
print(f"  Bottleneck           : {p['bottleneck_op']} @ {p['tact_time_sec']}s")
print(f"  Total cycle time     : {p['total_cycle_time_sec']}s")
print(f"  Total operators      : {p['total_operators']}")
print(f"  Total investment     : €{p['total_investment_eur']:,.0f}")
print(f"  Annual capacity      : {p['annual_capacity_at_tact']:,}")
print(f"  Gaps                 : {gap_rules}")
```

---

## Optimize Mode

When the process engineer provides confirmed data (replacing AI estimates with actual values):

1. Read existing `artifacts/n08-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which fields are being updated (compare new data vs existing assumptions):
   - Confirmed cycle times (S4/S5 → S1/S2)
   - Confirmed equipment specifications
   - Confirmed investment quotes from suppliers
   - Confirmed operator counts from production planning
4. Update only affected operations; preserve unchanged operations
5. Recalculate line summary (bottleneck may shift)
6. Recalculate `confidence_floor`
7. Remove resolved assumptions; update `process_version` (increment)
8. Write artifact → close log → write report
9. Run Validation

### When to fall back to Build mode

- **Operations added or removed** (new component added to BOM, process step eliminated)
- **Upstream n03 payload structure changed** (new components or component types)
- **Upstream n07 added new high-RPN failure modes** requiring new process controls
- **confidence_floor degraded** from S1/S2 to S4/S5 (data quality regression)

If uncertain, choose Build — full rebuild is safer than incomplete update.

**Key**: n08 is a high fan-out node. After Optimize, run `orchestrator.py affected n08` — typically impacts n10 (PFD), n12 (conversion cost), n13 (capacity), and indirectly n16 (RC) → n18 (quotation).

---

## Review Mode

Read-only quality check — no files modified:

1. Read `artifacts/n08-output.json`
2. Run Validation code above
3. Output quality summary:
   - Operation count, bottleneck, total investment
   - Coverage: make components with/without routes
   - DFMEA integration: high-RPN FMs covered/uncovered
   - confidence_floor, gaps list
4. Do not write artifact
