# NODE-18: Quotation（报价）

**Purpose**: Assemble the final quotation from RC (n16) + NRC (n17) + deliverables/part info (n01) + project timeline; HALT for human approval before submission.
**Input**: `artifacts/n16-output.json` (recurring cost), `artifacts/n17-output.json` (non-recurring cost), `artifacts/n01-output.json` (deliverables, part info)
**Output**: `artifacts/n18-output.json`
**Type**: human (HALT — quotation must be reviewed and approved by commercial/management before submission to customer)

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

# n18 upstream edges (from network.json):
#   n16 → n18 (normal)    — recurring cost (unit price)
#   n17 → n18 (normal)    — non-recurring cost
#   n01 → n18 (secondary) — deliverables, part info, customer requirements
upstream_ids = ['n16', 'n17']
secondary_ids = ['n01']
error_gaps_total = 0

for uid in upstream_ids:
    a = store.read(uid)
    assert a and a['status'] in ('ready', 'done'), \
        f"上游 {uid} 未完成 (status={a['status'] if a else 'missing'})"
    error_gaps = [g for g in a.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} 有 {len(error_gaps)} 个 error gap")

for uid in secondary_ids:
    a = store.read(uid)
    assert a and a['status'] in ('ready', 'done'), \
        f"辅助上游 {uid} 未完成 (status={a['status'] if a else 'missing'})"

if error_gaps_total:
    print(f"⚠ 上游共 {error_gaps_total} 个 error gap，报价结果需要重点审核")

log = NodeLogger('<project_path>', 'n18')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids + secondary_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read upstream artifacts — RC, NRC, requirements/deliverables")

n01 = store.read('n01')
n16 = store.read('n16')
n17 = store.read('n17')
n01_payload = n01['payload']
n16_payload = n16['payload']
n17_payload = n17['payload']
```

1. **Read n16 RC** (`artifacts/n16-output.json`):
   - `payload.total_rc_eur` — unit price (recurring cost per piece)
   - `payload.cost_breakdown_pct` — percentage breakdown for transparency
   - `payload.material_cost_eur`, `payload.conversion_cost_eur` — main cost drivers

2. **Read n17 NRC** (`artifacts/n17-output.json`):
   - `payload.total_nrc_eur` — total non-recurring cost
   - `payload.amortization_plan` — per-piece and per-year amortization
   - `payload.edd_total_eur`, `payload.tooling_investment_eur` — NRC breakdown

3. **Read n01 Requirements** (`artifacts/n01-output.json`):
   - `payload.part_number`, `payload.part_name` — part identification
   - `payload.customer`, `payload.program` — customer/program context
   - `payload.annual_volume` — for revenue calculation
   - `payload.deliverables` — list of required deliverables (samples, PPAP, documentation)
   - `payload.sop_date` — if available

```python
# RC data
unit_price = n16_payload.get('total_rc_eur', 0)
cost_breakdown = n16_payload.get('cost_breakdown_pct', {})
material_cost = n16_payload.get('material_cost_eur', 0)
conversion_cost = n16_payload.get('conversion_cost_eur', 0)

# NRC data
nrc_total = n17_payload.get('total_nrc_eur', 0)
amort_plan = n17_payload.get('amortization_plan', {})
edd_total = n17_payload.get('edd_total_eur', 0)
tooling_investment = n17_payload.get('tooling_investment_eur', 0)

# Part info from n01
part_number = n01_payload.get('part_number', '')
part_name = n01_payload.get('part_name', '')
customer = n01_payload.get('customer', '')
program = n01_payload.get('program', '')
annual_volume = n01_payload.get('annual_volume', 0)
deliverables = n01_payload.get('deliverables', [])
sop_date = n01_payload.get('sop_date', '')

log.info(f"Unit price (RC): {unit_price} EUR/pc")
log.info(f"NRC total: {nrc_total} EUR")
log.info(f"Part: {part_number} / {part_name}")
log.info(f"Customer: {customer}, Program: {program}")
log.info(f"Annual volume: {annual_volume}")
```

---

### Step 2: Collect all gaps and assumptions from upstream

```python
log.step("Step 2: Collect inherited gaps and assumptions from all upstream nodes")
```

The quotation must transparently report ALL unresolved gaps and assumptions from the entire upstream chain, so the reviewer knows the confidence level of each cost element.

```python
gaps = []
assumptions = []
inherited_gaps = []
inherited_assumptions = []

# Collect from all upstream nodes in the chain
upstream_nodes = ['n01', 'n16', 'n17']
# Also check deeper upstream via n16 (n11, n12) and n17 (n13, n15)
deep_upstream = ['n11', 'n12', 'n13', 'n15']

for nid in upstream_nodes + deep_upstream:
    node_art = store.read(nid)
    if node_art:
        for g in node_art.get('gaps', []):
            inherited_gaps.append({
                'source_node': nid,
                'rule': g['rule'],
                'msg': g['msg'],
                'severity': g['severity']
            })
        for a in node_art.get('assumptions', []):
            inherited_assumptions.append({
                'source_node': nid,
                'id': a['id'],
                'field': a['field'],
                'value': a['value'],
                'confidence': a['confidence']
            })

error_count = sum(1 for g in inherited_gaps if g['severity'] == 'error')
warning_count = sum(1 for g in inherited_gaps if g['severity'] == 'warning')

log.info(f"Inherited gaps: {error_count} error, {warning_count} warning")
log.info(f"Inherited assumptions: {len(inherited_assumptions)}")
```

---

### Step 3: Build quotation summary

```python
log.step("Step 3: Build quotation summary")
```

```python
# ── Annual revenue ───────────────────────────────────────────────────────────
annual_revenue = round(unit_price * annual_volume, 2) if annual_volume > 0 else 0

# ── Deliverables status ──────────────────────────────────────────────────────
# Check which deliverables from n01 are addressed by existing artifacts
deliverables_status = []
for d in deliverables:
    d_name = d if isinstance(d, str) else d.get('name', str(d))
    deliverables_status.append({
        'deliverable': d_name,
        'status': 'review_required'  # AI cannot confirm delivery — human must verify
    })

# ── Confidence summary ───────────────────────────────────────────────────────
# Aggregate confidence across all upstream nodes
node_confidences = {}
for nid in upstream_nodes + deep_upstream:
    node_art = store.read(nid)
    if node_art:
        node_confidences[nid] = node_art.get('confidence_floor', 'S5')

# ── Open items for customer ──────────────────────────────────────────────────
# Items that need customer input before quotation can be finalized
open_items = []
if error_count > 0:
    open_items.append(f"{error_count} upstream error gap(s) must be resolved before final quotation")
for g in inherited_gaps:
    if g['severity'] == 'error':
        open_items.append(f"[{g['source_node']}] {g['rule']}: {g['msg']}")

# Check for common open items
if not annual_volume or annual_volume_confidence == 'S4':
    open_items.append("Annual volume not confirmed by customer — affects unit price amortization")
if not sop_date:
    open_items.append("SOP date not confirmed — affects project timeline and EDD costs")

annual_volume_confidence = 'S1'
n01_gap_rules = [g['rule'] for g in n01.get('gaps', [])]
if 'R-01-01' in n01_gap_rules:
    annual_volume_confidence = 'S4'

log.info(f"Annual revenue: {annual_revenue} EUR")
log.info(f"Deliverables: {len(deliverables_status)}")
log.info(f"Open items: {len(open_items)}")
```

---

### Step 4: Determine overall confidence and gaps

```python
log.step("Step 4: Determine overall confidence floor and quotation gaps")
```

```python
# Overall confidence = worst across all upstream
CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
all_confs = list(node_confidences.values())
confidence_floor = max(all_confs, key=lambda c: CONFIDENCE_ORDER.get(c, 5)) if all_confs else 'S5'

# Quotation-level gaps
if error_count > 0:
    gaps.append({
        'rule': 'R-18-01',
        'msg': f'{error_count} upstream error gap(s) — quotation cannot be finalized until resolved',
        'severity': 'error'
    })

if warning_count > 5:
    gaps.append({
        'rule': 'R-18-02',
        'msg': f'{warning_count} upstream warnings — quotation confidence is limited; review assumptions',
        'severity': 'warning'
    })

if confidence_floor in ('S4', 'S5'):
    gaps.append({
        'rule': 'R-18-03',
        'msg': f'Overall confidence floor is {confidence_floor} — quotation contains significant assumptions',
        'severity': 'warning',
        'assumption': f'Confidence limited by: {", ".join(f"{k}={v}" for k,v in node_confidences.items() if v in ("S4","S5"))}'
    })

log.info(f"confidence_floor: {confidence_floor}")
log.info(f"Quotation gaps: {len(gaps)}")
```

---

### Step 5: Write artifact (HALT status)

```python
log.step("Step 5: Write artifact with HALT status for human review")
```

**CRITICAL**: This is a `human` type node. The artifact is written with `status: "waiting_human"` to HALT the pipeline. The quotation must be reviewed and approved by commercial/management before it can be submitted to the customer.

```python
artifact = {
    'node': 'n18',
    'project': '<project_id>',
    'status': 'waiting_human',  # HALT — requires human approval
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': [],  # Quotation itself has no new assumptions; all are inherited
    'payload': {
        'quotation_summary': {
            'part_number': part_number,
            'part_name': part_name,
            'customer': customer,
            'program': program,
            'unit_price_eur': unit_price,
            'nrc_total_eur': nrc_total,
            'annual_volume': annual_volume,
            'annual_revenue_eur': annual_revenue,
            'sop_date': sop_date
        },
        'price_breakdown': {
            'rc': {
                'material_cost_eur': material_cost,
                'conversion_cost_eur': conversion_cost,
                'logistics_eur': n16_payload.get('logistics_eur', 0),
                'quality_cost_eur': n16_payload.get('quality_cost_eur', 0),
                'overhead_eur': n16_payload.get('overhead_eur', 0),
                'profit_eur': n16_payload.get('profit_eur', 0),
                'total_rc_eur': unit_price
            },
            'nrc': {
                'edd_total_eur': edd_total,
                'tooling_investment_eur': tooling_investment,
                'additional_capex_eur': n17_payload.get('additional_capex_eur', 0),
                'total_nrc_eur': nrc_total,
                'amortization_plan': amort_plan
            }
        },
        'confidence_summary': node_confidences,
        'inherited_gaps': inherited_gaps,
        'inherited_assumptions_count': len(inherited_assumptions),
        'deliverables_status': deliverables_status,
        'open_items_for_customer': open_items
    }
}
store.write('n18', artifact)

# ── HALT message ─────────────────────────────────────────────────────────────
print("=" * 70)
print("HALT: Quotation ready for human review")
print("=" * 70)
print(f"Part:         {part_number} / {part_name}")
print(f"Customer:     {customer} — {program}")
print(f"Unit price:   {unit_price} EUR/pc")
print(f"NRC total:    {nrc_total} EUR")
print(f"Annual vol:   {annual_volume} pcs → Revenue: {annual_revenue} EUR/yr")
print(f"Confidence:   {confidence_floor}")
print(f"Error gaps:   {error_count}")
print(f"Warnings:     {warning_count}")
print(f"Open items:   {len(open_items)}")
print("=" * 70)
print("ACTION REQUIRED: Review and approve before submission to customer.")
print("Set status to 'done' after approval.")
print("=" * 70)
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
| — | `artifacts/n01-output.json` | Part info, deliverables, annual volume |
| — | `artifacts/n16-output.json` | Recurring cost (unit price breakdown) |
| — | `artifacts/n17-output.json` | Non-recurring cost (EDD, tooling, amortization) |
| — | `artifacts/n11-output.json` | Material cost (inherited gaps/assumptions) |
| — | `artifacts/n12-output.json` | Conversion cost (inherited gaps/assumptions) |
| — | `artifacts/n13-output.json` | Capacity analysis (inherited gaps/assumptions) |
| — | `artifacts/n15-output.json` | EDD costs (inherited gaps/assumptions) |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n18')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n18",
  "project": "<project_id>",
  "status": "waiting_human",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S4",
  "gaps": [
    {
      "rule": "R-18-03",
      "msg": "Overall confidence floor is S4 — quotation contains significant assumptions",
      "severity": "warning",
      "assumption": "Confidence limited by: n11=S4, n15=S4"
    }
  ],
  "assumptions": [],
  "payload": {
    "quotation_summary": {
      "part_number": "ABC-12345",
      "part_name": "Fuel Supply Assembly",
      "customer": "OEM-A",
      "program": "Platform-X",
      "unit_price_eur": 1.147,
      "nrc_total_eur": 445000,
      "annual_volume": 50000,
      "annual_revenue_eur": 57350,
      "sop_date": "2027-06-01"
    },
    "price_breakdown": {
      "rc": {
        "material_cost_eur": 0.85,
        "conversion_cost_eur": 0.80,
        "logistics_eur": 0.0825,
        "quality_cost_eur": 0.0495,
        "overhead_eur": 0.08,
        "profit_eur": 0.085,
        "total_rc_eur": 1.147
      },
      "nrc": {
        "edd_total_eur": 395000,
        "tooling_investment_eur": 50000,
        "additional_capex_eur": 0,
        "total_nrc_eur": 445000,
        "amortization_plan": {
          "amortization_years": 5,
          "annual_volume": 50000,
          "total_pieces": 250000,
          "nrc_per_piece_eur": 1.78,
          "nrc_per_year_eur": 89000
        }
      }
    },
    "confidence_summary": {
      "n01": "S2",
      "n11": "S4",
      "n12": "S3",
      "n13": "S3",
      "n15": "S4",
      "n16": "S4",
      "n17": "S4"
    },
    "inherited_gaps": [],
    "inherited_assumptions_count": 12,
    "deliverables_status": [
      {"deliverable": "PPAP Level 3", "status": "review_required"}
    ],
    "open_items_for_customer": [
      "Annual volume not confirmed by customer — affects unit price amortization"
    ]
  }
}
```

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-18-01 | Upstream error gaps exist — quotation cannot be finalized | error | Resolve all upstream errors before submitting quotation |
| R-18-02 | More than 5 upstream warnings — limited confidence | warning | Review all assumptions; consider requesting more data from customer |
| R-18-03 | Overall `confidence_floor` is S4 or S5 | warning | Quotation contains significant assumptions; communicate uncertainty to customer |

---

## Optimize Mode

When the user provides more precise data (e.g. customer confirms volume, supplier confirms pricing):

1. Read existing `artifacts/n18-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify what changed:
   - Upstream n16 or n17 re-run with better data -> re-read and update price breakdown
   - Customer confirmed annual volume or SOP date -> update quotation_summary
   - Deliverables status updated (e.g. PPAP samples shipped) -> update deliverables_status
   - Human reviewer resolved open items -> remove from open_items_for_customer
4. Recalculate annual_revenue, inherited gaps/assumptions counts
5. Recalculate `confidence_floor`
6. Write artifact (keep `status: waiting_human` unless explicitly approved)
7. Close log -> write report
8. Run Validation

### When to fall back to Build mode

- n16 or n17 payload structure changed fundamentally
- Customer requirements changed (new deliverables, different part scope)
- Multiple upstream nodes re-run simultaneously
- `confidence_floor` degraded from S1/S2 to S4/S5

If uncertain, choose Build — full reassembly is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n18-output.json`
2. Run Validation below
3. Summarize: unit price, NRC total, confidence floor, error/warning counts, open items
4. Check: is the quotation still consistent with current upstream artifacts?
5. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n18')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Quotation summary validation
qs = p.get('quotation_summary', {})
assert qs.get('unit_price_eur', 0) > 0, "unit_price_eur must be positive"
assert qs.get('nrc_total_eur') is not None, "nrc_total_eur missing"
assert qs.get('nrc_total_eur', 0) >= 0, "nrc_total_eur must be >= 0"
assert qs.get('annual_volume', 0) > 0, "annual_volume must be positive"
assert qs.get('annual_revenue_eur', 0) >= 0, "annual_revenue_eur must be >= 0"

# 3. Revenue consistency
expected_revenue = round(qs['unit_price_eur'] * qs['annual_volume'], 2)
assert abs(qs.get('annual_revenue_eur', 0) - expected_revenue) < 1.0, \
    f"annual_revenue ({qs.get('annual_revenue_eur')}) != unit_price × volume ({expected_revenue})"

# 4. Price breakdown must exist and be consistent
pb = p.get('price_breakdown', {})
rc = pb.get('rc', {})
nrc = pb.get('nrc', {})
assert rc.get('total_rc_eur', 0) > 0, "RC total_rc_eur must be positive"
assert abs(rc['total_rc_eur'] - qs['unit_price_eur']) < 0.01, \
    f"RC total ({rc['total_rc_eur']}) != quotation unit_price ({qs['unit_price_eur']})"
assert abs(nrc.get('total_nrc_eur', 0) - qs['nrc_total_eur']) < 1.0, \
    f"NRC total ({nrc.get('total_nrc_eur')}) != quotation nrc_total ({qs['nrc_total_eur']})"

# 5. Cross-check with n16 and n17
n16 = store.read('n16')
n17 = store.read('n17')
if n16:
    n16_rc = n16.get('payload', {}).get('total_rc_eur', 0)
    assert abs(rc['total_rc_eur'] - n16_rc) < 0.01, \
        f"RC mismatch: n18={rc['total_rc_eur']}, n16={n16_rc}"
if n17:
    n17_nrc = n17.get('payload', {}).get('total_nrc_eur', 0)
    assert abs(nrc.get('total_nrc_eur', 0) - n17_nrc) < 1.0, \
        f"NRC mismatch: n18={nrc.get('total_nrc_eur')}, n17={n17_nrc}"

# 6. Confidence summary must include key nodes
conf_summary = p.get('confidence_summary', {})
assert len(conf_summary) > 0, "confidence_summary is empty"

# 7. HALT check: status should be waiting_human (unless explicitly approved)
if artifact['status'] == 'waiting_human':
    print("⚠ Quotation is in HALT state — awaiting human approval")

# 8. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

print(f"✓ n18 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Part:          {qs.get('part_number')} / {qs.get('part_name')}")
print(f"  Unit price:    {qs['unit_price_eur']} EUR/pc")
print(f"  NRC total:     {qs['nrc_total_eur']} EUR")
print(f"  Annual volume: {qs['annual_volume']} pcs")
print(f"  Revenue:       {qs['annual_revenue_eur']} EUR/yr")
print(f"  Status:        {artifact['status']}")
print(f"  Inherited gaps:       {len(p.get('inherited_gaps', []))}")
print(f"  Inherited assumptions: {p.get('inherited_assumptions_count', 0)}")
print(f"  Open items:           {len(p.get('open_items_for_customer', []))}")
```
