# NODE-16: RC（单件成本 / Recurring Cost）

**Purpose**: Sum material cost (n11) + conversion cost (n12) + logistics + quality + overhead + profit = unit price for each piece produced.
**Input**: `artifacts/n11-output.json` (material cost per piece), `artifacts/n12-output.json` (conversion cost per piece)
**Output**: `artifacts/n16-output.json`
**Type**: auto (pure calculation from upstream cost data, no human input needed)

---

## Precondition Check

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# n16 upstream edges (from network.json):
#   n11 → n16 (normal)  — material cost per piece
#   n12 → n16 (normal)  — conversion cost per piece
upstream_ids = ['n11', 'n12']
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

log = NodeLogger('<project_path>', 'n16')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read input data from n11, n12")

n11 = store.read('n11')
n12 = store.read('n12')
n11_payload = n11['payload']
n12_payload = n12['payload']
```

1. **Read n11 Material Cost** (`artifacts/n11-output.json`):
   - `payload.total_material_cost_eur` — material cost per piece (sum of all BOM items)
   - `payload.items` — per-component material cost breakdown
   - Inherit any assumptions (material prices, scrap rates)

2. **Read n12 Conversion Cost** (`artifacts/n12-output.json`):
   - `payload.total_conversion_cost_eur` — conversion cost per piece (sum of all operations)
   - `payload.operations` — per-operation conversion cost breakdown
   - Inherit any assumptions (labor rates, machine rates, cycle times)

```python
material_cost = n11_payload.get('total_material_cost_eur', 0)
conversion_cost = n12_payload.get('total_conversion_cost_eur', 0)

log.info(f"Material cost (n11): {material_cost} EUR/pc")
log.info(f"Conversion cost (n12): {conversion_cost} EUR/pc")
```

---

### Step 2: Calculate overhead cost components

```python
log.step("Step 2: Calculate logistics, quality, overhead, and profit margin")
```

The unit price (RC) is built from these cost layers:

| Layer | Source | Calculation |
|-------|--------|-------------|
| Material cost | n11 | Direct from upstream |
| Conversion cost | n12 | Direct from upstream |
| Logistics | S4 estimate | % of (material + conversion) |
| Quality cost | S4 estimate | % of (material + conversion) |
| Overhead | S4 estimate | % of conversion cost |
| Profit margin | Company policy | % of total before profit |

```python
gaps = []
assumptions = []

# ── Logistics cost ───────────────────────────────────────────────────────────
# Inbound + outbound logistics, packaging — S4 industry estimate
LOGISTICS_PCT = 0.05  # 5% of (material + conversion)
base_cost = material_cost + conversion_cost
logistics_eur = round(base_cost * LOGISTICS_PCT, 4)
assumptions.append({
    'id': 'A-16-logistics',
    'field': 'logistics_eur',
    'value': str(logistics_eur),
    'unit': 'EUR/pc',
    'confidence': 'S4',
    'rationale': f'Logistics estimated as {LOGISTICS_PCT*100:.0f}% of (material + conversion); confirm with logistics department'
})

# ── Quality cost ─────────────────────────────────────────────────────────────
# Inspection, SPC, scrap management, customer quality — S4 industry estimate
QUALITY_PCT = 0.03  # 3% of (material + conversion)
quality_cost_eur = round(base_cost * QUALITY_PCT, 4)
assumptions.append({
    'id': 'A-16-quality',
    'field': 'quality_cost_eur',
    'value': str(quality_cost_eur),
    'unit': 'EUR/pc',
    'confidence': 'S4',
    'rationale': f'Quality cost estimated as {QUALITY_PCT*100:.0f}% of (material + conversion); confirm with quality department'
})

# ── Overhead ─────────────────────────────────────────────────────────────────
# General plant overhead (rent, utilities, IT, management) — S4 estimate
OVERHEAD_PCT = 0.10  # 10% of conversion cost
overhead_eur = round(conversion_cost * OVERHEAD_PCT, 4)
assumptions.append({
    'id': 'A-16-overhead',
    'field': 'overhead_eur',
    'value': str(overhead_eur),
    'unit': 'EUR/pc',
    'confidence': 'S4',
    'rationale': f'Overhead estimated as {OVERHEAD_PCT*100:.0f}% of conversion cost; confirm with controlling'
})

# ── Subtotal before profit ───────────────────────────────────────────────────
subtotal = material_cost + conversion_cost + logistics_eur + quality_cost_eur + overhead_eur

# ── Profit margin ────────────────────────────────────────────────────────────
PROFIT_MARGIN_PCT = 0.08  # 8%, S4 company target
profit_eur = round(subtotal * PROFIT_MARGIN_PCT, 4)
assumptions.append({
    'id': 'A-16-profit',
    'field': 'profit_margin_pct',
    'value': str(PROFIT_MARGIN_PCT * 100),
    'unit': '%',
    'confidence': 'S4',
    'rationale': f'Profit margin {PROFIT_MARGIN_PCT*100:.0f}% is company target; adjust per project strategy'
})

# ── Total RC ─────────────────────────────────────────────────────────────────
total_rc_eur = round(subtotal + profit_eur, 4)

log.info(f"Material:    {material_cost} EUR/pc")
log.info(f"Conversion:  {conversion_cost} EUR/pc")
log.info(f"Logistics:   {logistics_eur} EUR/pc ({LOGISTICS_PCT*100:.0f}%)")
log.info(f"Quality:     {quality_cost_eur} EUR/pc ({QUALITY_PCT*100:.0f}%)")
log.info(f"Overhead:    {overhead_eur} EUR/pc ({OVERHEAD_PCT*100:.0f}%)")
log.info(f"Subtotal:    {subtotal} EUR/pc")
log.info(f"Profit:      {profit_eur} EUR/pc ({PROFIT_MARGIN_PCT*100:.0f}%)")
log.info(f"Total RC:    {total_rc_eur} EUR/pc")
```

---

### Step 3: Gap identification and confidence

```python
log.step("Step 3: Gap identification and confidence floor")
```

```python
# R-16-01: overhead cost components use assumptions
gaps.append({
    'rule': 'R-16-01',
    'msg': f'Logistics ({LOGISTICS_PCT*100:.0f}%), quality ({QUALITY_PCT*100:.0f}%), overhead ({OVERHEAD_PCT*100:.0f}%), profit ({PROFIT_MARGIN_PCT*100:.0f}%) are S4 assumptions — confirm with controlling',
    'severity': 'warning',
    'assumption': 'All percentage-based adders are industry estimates'
})

# Inherit upstream assumptions
n11_assumptions = n11.get('assumptions', [])
n12_assumptions = n12.get('assumptions', [])
inherited_count = len(n11_assumptions) + len(n12_assumptions)
if inherited_count > 0:
    log.info(f"Inherited {inherited_count} assumptions from n11 ({len(n11_assumptions)}) + n12 ({len(n12_assumptions)})")

# Propagate upstream gaps as informational
n11_gaps = [g for g in n11.get('gaps', []) if g['severity'] in ('warning', 'error')]
n12_gaps = [g for g in n12.get('gaps', []) if g['severity'] in ('warning', 'error')]
if n11_gaps or n12_gaps:
    log.warn(f"Upstream gaps inherited: n11={len(n11_gaps)}, n12={len(n12_gaps)}")

# Confidence floor: S4 at best (due to logistics/quality/overhead/profit assumptions)
# Could be worse if n11 or n12 have S5 confidence
CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
upstream_confs = [
    n11.get('confidence_floor', 'S5'),
    n12.get('confidence_floor', 'S5')
]
worst_upstream = max(upstream_confs, key=lambda c: CONFIDENCE_ORDER.get(c, 5))
confidence_floor = max(['S4', worst_upstream], key=lambda c: CONFIDENCE_ORDER.get(c, 5))

log.info(f"confidence_floor: {confidence_floor}")
log.info(f"Gaps: {len(gaps)}")
```

---

### Step 4: Write artifact

```python
log.step("Step 4: Write artifact")

artifact = {
    'node': 'n16',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'material_cost_eur': material_cost,
        'conversion_cost_eur': conversion_cost,
        'logistics_eur': logistics_eur,
        'quality_cost_eur': quality_cost_eur,
        'overhead_eur': overhead_eur,
        'profit_margin_pct': PROFIT_MARGIN_PCT * 100,
        'profit_eur': profit_eur,
        'total_rc_eur': total_rc_eur,
        'cost_breakdown_pct': {
            'material': round(material_cost / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0,
            'conversion': round(conversion_cost / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0,
            'logistics': round(logistics_eur / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0,
            'quality': round(quality_cost_eur / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0,
            'overhead': round(overhead_eur / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0,
            'profit': round(profit_eur / total_rc_eur * 100, 1) if total_rc_eur > 0 else 0
        }
    }
}
store.write('n16', artifact)
```

### Step 5: Close log

```python
log.done(artifact)
```

### Step 6: Write report

```python
from reporter import NodeReport

# AI fills this based on actual execution — all four subsections are mandatory
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n11-output.json` | Material cost per piece (total + per-item breakdown) |
| — | `artifacts/n12-output.json` | Conversion cost per piece (total + per-operation breakdown) |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n16')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n16",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S4",
  "gaps": [
    {
      "rule": "R-16-01",
      "msg": "Logistics (5%), quality (3%), overhead (10%), profit (8%) are S4 assumptions — confirm with controlling",
      "severity": "warning",
      "assumption": "All percentage-based adders are industry estimates"
    }
  ],
  "assumptions": [
    {
      "id": "A-16-logistics",
      "field": "logistics_eur",
      "value": "0.0825",
      "unit": "EUR/pc",
      "confidence": "S4",
      "rationale": "Logistics estimated as 5% of (material + conversion); confirm with logistics department"
    }
  ],
  "payload": {
    "material_cost_eur": 0.85,
    "conversion_cost_eur": 0.80,
    "logistics_eur": 0.0825,
    "quality_cost_eur": 0.0495,
    "overhead_eur": 0.08,
    "profit_margin_pct": 8,
    "profit_eur": 0.0850,
    "total_rc_eur": 1.147,
    "cost_breakdown_pct": {
      "material": 41.2,
      "conversion": 38.8,
      "logistics": 4.0,
      "quality": 2.4,
      "overhead": 3.9,
      "profit": 4.1
    }
  }
}
```

---

## Calculation Reference

### Unit price formula

```
total_rc = material_cost + conversion_cost + logistics + quality + overhead + profit

Where:
  logistics      = (material + conversion) × LOGISTICS_PCT
  quality_cost   = (material + conversion) × QUALITY_PCT
  overhead       = conversion_cost × OVERHEAD_PCT
  profit         = subtotal × PROFIT_MARGIN_PCT
  subtotal       = material + conversion + logistics + quality + overhead
```

### Default percentages (S4, industry estimates)

| Adder | Base | Default % | Typical range |
|-------|------|-----------|---------------|
| Logistics | material + conversion | 5% | 3-8% |
| Quality | material + conversion | 3% | 2-5% |
| Overhead | conversion only | 10% | 8-15% |
| Profit | subtotal | 8% | 5-12% |

These percentages are initial S4 estimates. Replace with company-specific rates during Optimize.

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-16-01 | Logistics, quality, overhead, profit percentages are S4 assumptions | warning | Confirm with controlling / finance department |

---

## Optimize Mode

When the user provides more precise data (replacing S4 assumptions with S1/S2 actuals):

1. Read existing `artifacts/n16-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which cost components are updated:
   - Actual logistics rate from logistics department (S4 -> S1)
   - Actual overhead allocation from controlling (S4 -> S1)
   - Confirmed profit margin from management (S4 -> S2)
   - Updated material cost from n11 re-run
   - Updated conversion cost from n12 re-run
4. Recalculate total_rc_eur and cost_breakdown_pct
5. Recalculate `confidence_floor`
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 4/5/6)
8. Run Validation

### When to fall back to Build mode

- n11 or n12 payload structure changed (new cost categories)
- Cost model fundamentally changed (e.g. switching from percentage-based to activity-based costing)
- `confidence_floor` degraded from S1/S2 to S4/S5

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n16-output.json`
2. Run Validation below
3. Summarize: total RC, cost breakdown percentages, gaps count, assumptions count, confidence_floor
4. Sanity check: is material+conversion > 70% of total? (If not, overhead assumptions may be too high)
5. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n16')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
assert p.get('material_cost_eur', 0) >= 0, "material_cost_eur must be >= 0"
assert p.get('conversion_cost_eur', 0) >= 0, "conversion_cost_eur must be >= 0"
assert p.get('logistics_eur', 0) >= 0, "logistics_eur must be >= 0"
assert p.get('quality_cost_eur', 0) >= 0, "quality_cost_eur must be >= 0"
assert p.get('overhead_eur', 0) >= 0, "overhead_eur must be >= 0"
assert p.get('total_rc_eur', 0) > 0, "total_rc_eur must be positive"

# 3. Total must be sum of components
expected_subtotal = (p['material_cost_eur'] + p['conversion_cost_eur'] +
                     p['logistics_eur'] + p['quality_cost_eur'] + p['overhead_eur'])
expected_total = expected_subtotal + p.get('profit_eur', 0)
assert abs(p['total_rc_eur'] - expected_total) < 0.01, \
    f"total_rc_eur ({p['total_rc_eur']}) != sum of components ({expected_total})"

# 4. Profit margin range check
profit_pct = p.get('profit_margin_pct', 0)
assert 0 <= profit_pct <= 30, \
    f"profit_margin_pct ({profit_pct}) outside reasonable range (0-30%)"

# 5. Cost breakdown percentages should sum to ~100%
breakdown = p.get('cost_breakdown_pct', {})
if breakdown:
    pct_sum = sum(breakdown.values())
    assert 98 <= pct_sum <= 102, \
        f"cost_breakdown_pct sums to {pct_sum}%, expected ~100%"

# 6. Cross-check with n11 and n12
n11 = store.read('n11')
n12 = store.read('n12')
if n11:
    n11_total = n11.get('payload', {}).get('total_material_cost_eur', 0)
    assert abs(p['material_cost_eur'] - n11_total) < 0.01, \
        f"material_cost mismatch: n16={p['material_cost_eur']}, n11={n11_total}"
if n12:
    n12_total = n12.get('payload', {}).get('total_conversion_cost_eur', 0)
    assert abs(p['conversion_cost_eur'] - n12_total) < 0.01, \
        f"conversion_cost mismatch: n16={p['conversion_cost_eur']}, n12={n12_total}"

# 7. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

print(f"✓ n16 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Material cost:    {p['material_cost_eur']} EUR/pc")
print(f"  Conversion cost:  {p['conversion_cost_eur']} EUR/pc")
print(f"  Logistics:        {p['logistics_eur']} EUR/pc")
print(f"  Quality:          {p['quality_cost_eur']} EUR/pc")
print(f"  Overhead:         {p['overhead_eur']} EUR/pc")
print(f"  Profit:           {p.get('profit_eur', 0)} EUR/pc ({profit_pct}%)")
print(f"  Total RC:         {p['total_rc_eur']} EUR/pc")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
