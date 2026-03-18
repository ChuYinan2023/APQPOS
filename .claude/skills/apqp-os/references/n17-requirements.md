# NODE-17: NRC（一次性费用 / Non-Recurring Cost）

**Purpose**: Sum all one-time costs: EDD engineering costs (n15) + capacity investment (n13) + additional capital expenditure = total NRC with amortization plan.
**Input**: `artifacts/n13-output.json` (capacity — additional investment data), `artifacts/n15-output.json` (EDD — engineering development costs)
**Output**: `artifacts/n17-output.json`
**Type**: auto (pure aggregation from upstream cost data, no human input needed)

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

# n17 upstream edges (from network.json):
#   n13 → n17 (normal)  — capacity analysis with investment needs
#   n15 → n17 (normal)  — EDD engineering development costs
upstream_ids = ['n13', 'n15']
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

# Also read n01 for annual_volume (needed for amortization calculation)
n01 = store.read('n01')
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 未完成 (status={n01['status'] if n01 else 'missing'})"

log = NodeLogger('<project_path>', 'n17')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
log.info(f"n01: status={store.get_status('n01')}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read upstream artifacts — EDD costs, capacity investment, annual volume")

n01_payload = n01['payload']
n13 = store.read('n13')
n15 = store.read('n15')
n13_payload = n13['payload']
n15_payload = n15['payload']
```

1. **Read n15 EDD** (`artifacts/n15-output.json`):
   - `payload.total_edd_eur` — total engineering development costs
   - `payload.cost_items` — breakdown by category (tooling, fixtures, testing, etc.)

2. **Read n13 Capacity** (`artifacts/n13-output.json`):
   - `payload.additional_investment_needed` — boolean flag
   - `payload.operation_capacities` — per-operation equipment investment
   - Derive `tooling_investment_eur` from n08 operations (via n13 data)

3. **Read n01** (`artifacts/n01-output.json`):
   - `payload.annual_volume` — needed for amortization per-piece calculation
   - `payload.project_lifetime_years` — if available; otherwise assume S4 default

```python
# EDD from n15
edd_total = n15_payload.get('total_edd_eur', 0)
edd_items = n15_payload.get('cost_items', [])

# Capacity investment from n13
additional_investment_needed = n13_payload.get('additional_investment_needed', False)
op_capacities = n13_payload.get('operation_capacities', [])
tooling_investment = sum(oc.get('equipment_investment_eur', 0) for oc in op_capacities)

# Annual volume from n01
annual_volume = n01_payload.get('annual_volume', 50000)
annual_volume_confidence = 'S1'
n01_gap_rules = [g['rule'] for g in n01.get('gaps', [])]
if 'R-01-01' in n01_gap_rules or annual_volume is None:
    if annual_volume is None:
        annual_volume = 50000
    annual_volume_confidence = 'S4'

# Project lifetime
project_lifetime_years = n01_payload.get('project_lifetime_years', 0)

log.info(f"EDD total (n15): {edd_total} EUR")
log.info(f"Tooling investment (n13/n08): {tooling_investment} EUR")
log.info(f"Additional investment needed: {additional_investment_needed}")
log.info(f"Annual volume: {annual_volume} (confidence: {annual_volume_confidence})")
log.info(f"Project lifetime: {project_lifetime_years} years")
```

---

### Step 2: Build NRC breakdown

```python
log.step("Step 2: Build NRC breakdown and calculate total")
```

NRC is composed of:

| Component | Source | Description |
|-----------|--------|-------------|
| `edd_total_eur` | n15 | Engineering development costs (all categories) |
| `tooling_investment_eur` | n08 via n13 | Production equipment and tooling investment |
| `additional_capex_eur` | Estimate | Additional capital expenditure not covered above (facility modifications, special utilities, etc.) |

```python
gaps = []
assumptions = []

# ── EDD total ────────────────────────────────────────────────────────────────
edd_total_eur = edd_total
log.info(f"EDD total: {edd_total_eur} EUR")

# ── Tooling investment ───────────────────────────────────────────────────────
# Tooling from n08 operations captured in n13 capacity analysis
# Note: n15 may also include tooling as a cost_item — avoid double counting
# Check if n15 tooling is already included in tooling_investment
n15_tooling = 0
for ci in edd_items:
    if ci.get('category') == 'tooling':
        n15_tooling = ci.get('estimated_cost_eur', 0)
        break

# If n15 already includes tooling from n08, use the larger of the two
# (they may represent different scopes: n15 tooling = EDD-phase tools, n13 = production tools)
if n15_tooling > 0 and tooling_investment > 0:
    # Assume n15 tooling is included in EDD and n13 tooling is separate production equipment
    tooling_investment_eur = tooling_investment
    log.info(f"Tooling: n15 includes {n15_tooling} EUR (in EDD), n13 adds {tooling_investment} EUR (production equipment)")
elif tooling_investment > 0:
    tooling_investment_eur = tooling_investment
else:
    tooling_investment_eur = 0

# ── Additional CAPEX ─────────────────────────────────────────────────────────
# Facility modifications, special utilities, environmental compliance — S4 estimate
# Default to 0 unless specific needs are identified from n13
additional_capex_eur = 0
if additional_investment_needed and tooling_investment_eur == 0:
    # n13 says investment needed but no specific amount — flag as gap
    gaps.append({
        'rule': 'R-17-02',
        'msg': 'n13 indicates additional_investment_needed=true but no specific amount provided',
        'severity': 'warning'
    })

# ── Total NRC ────────────────────────────────────────────────────────────────
total_nrc_eur = edd_total_eur + tooling_investment_eur + additional_capex_eur

log.info(f"EDD:                {edd_total_eur} EUR")
log.info(f"Tooling investment: {tooling_investment_eur} EUR")
log.info(f"Additional CAPEX:   {additional_capex_eur} EUR")
log.info(f"Total NRC:          {total_nrc_eur} EUR")
```

---

### Step 3: Calculate amortization plan

```python
log.step("Step 3: Calculate amortization plan")
```

Amortization options:
- **Per-piece**: `nrc_per_piece = total_nrc / (annual_volume x amortization_years)`
- **Per-year**: `nrc_per_year = total_nrc / amortization_years`

```python
# Default amortization period
DEFAULT_AMORT_YEARS = 5  # S4, typical automotive project lifetime
amort_years = project_lifetime_years if project_lifetime_years > 0 else DEFAULT_AMORT_YEARS
amort_years_confidence = 'S1' if project_lifetime_years > 0 else 'S4'

if amort_years_confidence == 'S4':
    assumptions.append({
        'id': 'A-17-amort-years',
        'field': 'amortization_years',
        'value': str(amort_years),
        'unit': 'years',
        'confidence': 'S4',
        'rationale': f'Default {DEFAULT_AMORT_YEARS}-year amortization; confirm project lifetime with customer'
    })

total_pieces = annual_volume * amort_years
nrc_per_piece = round(total_nrc_eur / total_pieces, 4) if total_pieces > 0 else 0
nrc_per_year = round(total_nrc_eur / amort_years, 2) if amort_years > 0 else 0

amortization_plan = {
    'amortization_years': amort_years,
    'amortization_years_confidence': amort_years_confidence,
    'annual_volume': annual_volume,
    'total_pieces': total_pieces,
    'nrc_per_piece_eur': nrc_per_piece,
    'nrc_per_year_eur': nrc_per_year
}

log.info(f"Amortization: {amort_years} years × {annual_volume} pcs/yr = {total_pieces} pieces total")
log.info(f"NRC per piece: {nrc_per_piece} EUR")
log.info(f"NRC per year:  {nrc_per_year} EUR")
```

---

### Step 4: Gap identification and confidence

```python
log.step("Step 4: Gap identification and confidence floor")
```

```python
# R-17-01: investment estimates are assumptions
if total_nrc_eur > 0:
    gaps.append({
        'rule': 'R-17-01',
        'msg': f'NRC total ({total_nrc_eur} EUR) based on upstream estimates — confirm tooling quotes and EDD budget',
        'severity': 'warning',
        'assumption': 'All NRC components are estimates pending supplier/internal confirmation'
    })

# Inherit annual_volume assumption
if annual_volume_confidence != 'S1':
    assumptions.append({
        'id': 'A-17-annual-volume',
        'field': 'annual_volume',
        'value': str(annual_volume),
        'unit': '件/年',
        'confidence': annual_volume_confidence,
        'rationale': 'Inherited from n01 — affects amortization per-piece calculation'
    })

# Confidence floor: worst of upstream + own assumptions
CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
all_confs = [
    n13.get('confidence_floor', 'S5'),
    n15.get('confidence_floor', 'S5'),
    amort_years_confidence,
    annual_volume_confidence
]
confidence_floor = max(all_confs, key=lambda c: CONFIDENCE_ORDER.get(c, 5))

log.info(f"confidence_floor: {confidence_floor}")
log.info(f"Gaps: {len(gaps)}")
```

---

### Step 5: Write artifact

```python
log.step("Step 5: Write artifact")

artifact = {
    'node': 'n17',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'edd_total_eur': edd_total_eur,
        'tooling_investment_eur': tooling_investment_eur,
        'additional_capex_eur': additional_capex_eur,
        'total_nrc_eur': total_nrc_eur,
        'amortization_plan': amortization_plan
    }
}
store.write('n17', artifact)
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
| — | `artifacts/n01-output.json` | annual_volume, project_lifetime_years |
| — | `artifacts/n13-output.json` | Capacity analysis, equipment investment, additional_investment_needed |
| — | `artifacts/n15-output.json` | EDD cost items, total_edd_eur |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n17')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n17",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S4",
  "gaps": [
    {
      "rule": "R-17-01",
      "msg": "NRC total (445000 EUR) based on upstream estimates — confirm tooling quotes and EDD budget",
      "severity": "warning",
      "assumption": "All NRC components are estimates pending supplier/internal confirmation"
    }
  ],
  "assumptions": [
    {
      "id": "A-17-amort-years",
      "field": "amortization_years",
      "value": "5",
      "unit": "years",
      "confidence": "S4",
      "rationale": "Default 5-year amortization; confirm project lifetime with customer"
    }
  ],
  "payload": {
    "edd_total_eur": 395000,
    "tooling_investment_eur": 50000,
    "additional_capex_eur": 0,
    "total_nrc_eur": 445000,
    "amortization_plan": {
      "amortization_years": 5,
      "amortization_years_confidence": "S4",
      "annual_volume": 50000,
      "total_pieces": 250000,
      "nrc_per_piece_eur": 1.78,
      "nrc_per_year_eur": 89000
    }
  }
}
```

---

## Calculation Reference

### NRC total

```
total_nrc = edd_total + tooling_investment + additional_capex
```

### Amortization

```
nrc_per_piece = total_nrc / (annual_volume × amortization_years)
nrc_per_year  = total_nrc / amortization_years
```

### Double-counting avoidance

n15 EDD may include a "tooling" category for development tools (e.g., prototype molds). n13 references n08 production tooling. These are typically different scopes:
- **n15 tooling**: prototype tools, soft tools, pre-series tools
- **n13/n08 tooling**: production-grade tools, hard tools

If the project uses the same tool for both (e.g., single-cavity mold for both proto and production), consolidate and note in assumptions.

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-17-01 | NRC components are upstream estimates — not confirmed quotes | warning | Confirm tooling quotes with suppliers, EDD budget with project controller |
| R-17-02 | n13 `additional_investment_needed=true` but no specific amount | warning | Request investment estimate from production planning |

---

## Optimize Mode

When the user provides more precise data (replacing S4 assumptions with S1/S2 actuals):

1. Read existing `artifacts/n17-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which NRC components are updated:
   - Confirmed tooling quotes from suppliers (S4 -> S1)
   - Updated EDD from n15 re-run
   - Confirmed project lifetime from customer (S4 -> S1)
   - Confirmed annual volume from customer (affects amortization)
4. Recalculate total_nrc_eur and amortization_plan
5. Recalculate `confidence_floor`
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 5/6/7)
8. Run Validation

### When to fall back to Build mode

- n15 EDD restructured (new cost categories added/removed)
- n13 capacity analysis fundamentally changed (new equipment required)
- Amortization model changed (e.g. from per-piece to lump-sum billing)
- `confidence_floor` degraded from S1/S2 to S4/S5

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n17-output.json`
2. Run Validation below
3. Summarize: NRC total, breakdown, amortization per-piece, gaps count, assumptions count, confidence_floor
4. Sanity check: is NRC per-piece reasonable relative to RC (n16)?
5. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n17')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
assert p.get('edd_total_eur') is not None, "edd_total_eur missing"
assert p.get('edd_total_eur', 0) >= 0, "edd_total_eur must be >= 0"
assert p.get('tooling_investment_eur') is not None, "tooling_investment_eur missing"
assert p.get('tooling_investment_eur', 0) >= 0, "tooling_investment_eur must be >= 0"
assert p.get('additional_capex_eur') is not None, "additional_capex_eur missing"
assert p.get('additional_capex_eur', 0) >= 0, "additional_capex_eur must be >= 0"
assert p.get('total_nrc_eur', 0) >= 0, "total_nrc_eur must be >= 0"

# 3. Total must equal sum of components
expected_total = p['edd_total_eur'] + p['tooling_investment_eur'] + p['additional_capex_eur']
assert abs(p['total_nrc_eur'] - expected_total) < 1.0, \
    f"total_nrc_eur ({p['total_nrc_eur']}) != sum of components ({expected_total})"

# 4. Amortization plan validation
amort = p.get('amortization_plan', {})
assert amort.get('amortization_years', 0) > 0, "amortization_years must be positive"
assert amort.get('annual_volume', 0) > 0, "annual_volume must be positive"
assert amort.get('total_pieces', 0) > 0, "total_pieces must be positive"

# Verify amortization math
expected_pieces = amort['annual_volume'] * amort['amortization_years']
assert amort['total_pieces'] == expected_pieces, \
    f"total_pieces ({amort['total_pieces']}) != annual_volume × years ({expected_pieces})"

if p['total_nrc_eur'] > 0:
    expected_per_piece = round(p['total_nrc_eur'] / amort['total_pieces'], 4)
    assert abs(amort.get('nrc_per_piece_eur', 0) - expected_per_piece) < 0.01, \
        f"nrc_per_piece ({amort.get('nrc_per_piece_eur')}) != expected ({expected_per_piece})"

# 5. Cross-check with n15
n15 = store.read('n15')
if n15:
    n15_total = n15.get('payload', {}).get('total_edd_eur', 0)
    assert abs(p['edd_total_eur'] - n15_total) < 1.0, \
        f"edd_total mismatch: n17={p['edd_total_eur']}, n15={n15_total}"

# 6. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

print(f"✓ n17 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  EDD total:           {p['edd_total_eur']} EUR")
print(f"  Tooling investment:  {p['tooling_investment_eur']} EUR")
print(f"  Additional CAPEX:    {p['additional_capex_eur']} EUR")
print(f"  Total NRC:           {p['total_nrc_eur']} EUR")
print(f"  Amortization:        {amort['amortization_years']} years, {amort['nrc_per_piece_eur']} EUR/pc")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
