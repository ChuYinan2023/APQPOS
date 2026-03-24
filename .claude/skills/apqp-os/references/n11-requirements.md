# NODE-11: Material Cost（物料成本）

**Purpose**: Calculate material cost per piece for each BOM item using n05 material prices and n06 quantities; sum into total material cost per assembly.
**Input**: `artifacts/n05-output.json` (material selections with prices), `artifacts/n06-output.json` (weights/quantities), `artifacts/n08-output.json` (process scrap adjustment — secondary)
**Output**: `artifacts/n11-output.json`
**Type**: auto (pure calculation, no human input needed)

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

# n11 upstream edges (from network.json):
#   n05 → n11 (normal)    — material selections with unit prices
#   n06 → n11 (normal)    — quantity calc with gross weights
#   n08 → n11 (secondary) — process route (scrap adjustment context)
upstream_ids = ['n05', 'n06']
error_gaps_total = 0
for uid in upstream_ids:
    a = store.read(uid)
    assert a and a['status'] in ('ready', 'done'), \
        f"上游 {uid} 未完成 (status={a['status'] if a else 'missing'})"
    error_gaps = [g for g in a.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} 有 {len(error_gaps)} 个 error gap")

# n08 is secondary — read if available, but do not block
n08 = store.read('n08')
n08_available = n08 and n08['status'] in ('ready', 'done')
if n08_available:
    n08_error_gaps = [g for g in n08.get('gaps', []) if g['severity'] == 'error']
    if n08_error_gaps:
        error_gaps_total += len(n08_error_gaps)
        print(f"⚠ n08 有 {len(n08_error_gaps)} 个 error gap")
else:
    print("ℹ n08 (Process Route) not available — proceeding without process scrap adjustment")

if error_gaps_total:
    print(f"⚠ 上游共 {error_gaps_total} 个 error gap，本节点结果可能不可靠")

log = NodeLogger('<project_path>', 'n11')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
log.info(f"n08: status={store.get_status('n08') if n08_available else 'not available (secondary)'}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read input data from n05, n06, n08")

n05 = store.read('n05')
n06 = store.read('n06')
n05_payload = n05['payload']
n06_payload = n06['payload']

# ── From n05: material selections with unit prices ──────────────────────────
n05_items = n05_payload.get('items', [])
log.info(f"n05 material selections: {len(n05_items)}")

# Build lookup: component_ref -> material price info
price_lookup = {}
for item in n05_items:
    ref = item.get('component_ref')
    if ref:
        price_lookup[ref] = {
            'material_name': item.get('material_name', ''),
            'unit_price_eur_kg': item.get('unit_price_eur_kg'),
            'price_source': item.get('price_source', ''),
            'confidence': item.get('confidence', 'S4'),
        }

# ── From n06: quantity calc with gross weights ──────────────────────────────
n06_items = n06_payload.get('items', [])
log.info(f"n06 quantity items: {len(n06_items)}")

# Build lookup: component_ref -> weight info
weight_lookup = {}
for item in n06_items:
    ref = item.get('component_ref')
    if ref:
        weight_lookup[ref] = {
            'gross_weight_g': item.get('gross_weight_g'),
            'net_weight_g': item.get('net_weight_g'),
            'confidence': item.get('confidence', 'S4'),
        }

# ── From n08 (secondary): process route scrap context ──────────────────────
n08_payload = n08.get('payload', {}) if n08_available else {}
n08_operations = n08_payload.get('operations', [])
log.info(f"n08 operations: {len(n08_operations)} (secondary context)")

# Build lookup: component_ref -> process scrap adjustments from n08
process_scrap_lookup = {}
for op in n08_operations:
    ref = op.get('component_ref')
    if ref and op.get('scrap_rate_pct') is not None:
        process_scrap_lookup[ref] = {
            'scrap_rate_pct': op.get('scrap_rate_pct'),
            'process': op.get('process', ''),
        }
```

---

### Step 2: Determine complete item list

```python
log.step("Step 2: Determine complete item list from n05 + n06")

# Merge component refs from both n05 and n06 to catch any mismatches
all_refs = set(price_lookup.keys()) | set(weight_lookup.keys())
log.info(f"Unique component refs: {len(all_refs)}")
log.info(f"  In n05 (prices): {len(price_lookup)}")
log.info(f"  In n06 (weights): {len(weight_lookup)}")

# Identify BOM item types from n05 (make vs buy)
# make items: material_cost = gross_weight × unit_price
# buy items: use catalog/estimate price directly
```

---

### Step 3: Calculate material cost per piece

```python
log.step("Step 3: Calculate material cost per piece for each item")

items = []
gaps = []
assumptions = []
confidence_levels = []

for ref in sorted(all_refs):
    price_info = price_lookup.get(ref, {})
    weight_info = weight_lookup.get(ref, {})

    material_name = price_info.get('material_name', '')
    unit_price_eur_kg = price_info.get('unit_price_eur_kg')
    price_source = price_info.get('price_source', '')
    gross_weight_g = weight_info.get('gross_weight_g')
    price_confidence = price_info.get('confidence', 'S5')
    weight_confidence = weight_info.get('confidence', 'S5')

    cost_per_piece_eur = None
    cost_source = 'calculated'
    item_confidence = 'S2'

    # ── Determine if make or buy item ────────────────────────────────────────
    # n05 items with material_name + unit_price_eur_kg are "make" items
    # n05 items with catalog_price_eur or buy_price_eur are "buy" items
    buy_price = price_info.get('catalog_price_eur') or price_info.get('buy_price_eur')
    is_buy_item = buy_price is not None

    if is_buy_item:
        # ── Buy item: use catalog/estimate price directly ────────────────────
        cost_per_piece_eur = buy_price
        cost_source = 'catalog' if price_info.get('catalog_price_eur') else 'estimated'
        item_confidence = price_confidence
        log.info(f"{ref}: BUY — cost={cost_per_piece_eur} EUR ({cost_source})")

    else:
        # ── Make item: material_cost = gross_weight_kg × unit_price_eur_kg ───
        if unit_price_eur_kg is None:
            gaps.append({
                'rule': 'R-11-01',
                'msg': f'{ref}: missing material unit price (EUR/kg) — cannot calculate cost',
                'severity': 'warning'
            })
            log.warn(f"{ref}: missing unit_price_eur_kg — R-11-01 gap")
            item_confidence = 'S5'

        if gross_weight_g is None:
            gaps.append({
                'rule': 'R-11-02',
                'msg': f'{ref}: missing gross weight — using estimate if available',
                'severity': 'warning'
            })
            log.warn(f"{ref}: missing gross_weight_g — R-11-02 gap")
            # Try net_weight_g as fallback with 10% scrap assumption
            net_weight_g = weight_info.get('net_weight_g')
            if net_weight_g is not None:
                gross_weight_g = net_weight_g * 1.10  # assume 10% scrap
                assumptions.append({
                    'id': f'A-{ref}-gross-weight',
                    'field': f'{ref}.gross_weight_g',
                    'value': str(round(gross_weight_g, 2)),
                    'unit': 'g',
                    'confidence': 'S4',
                    'rationale': f'gross_weight estimated from net_weight × 1.10 (10% scrap assumption)'
                })
                item_confidence = 'S4'
            else:
                item_confidence = 'S5'

        if unit_price_eur_kg is not None and gross_weight_g is not None:
            gross_weight_kg = gross_weight_g / 1000.0
            cost_per_piece_eur = round(gross_weight_kg * unit_price_eur_kg, 4)
            cost_source = 'calculated'
            log.info(f"{ref}: MAKE — {gross_weight_g}g × {unit_price_eur_kg} EUR/kg = {cost_per_piece_eur} EUR")
        else:
            log.warn(f"{ref}: cannot calculate cost — missing price or weight")

    # ── Determine item confidence ────────────────────────────────────────────
    CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
    worst_input = max(
        CONFIDENCE_ORDER.get(price_confidence, 5),
        CONFIDENCE_ORDER.get(weight_confidence, 5)
    )
    # item_confidence cannot be better than worst input
    if CONFIDENCE_ORDER.get(item_confidence, 5) < worst_input:
        for k, v in CONFIDENCE_ORDER.items():
            if v == worst_input:
                item_confidence = k
                break

    confidence_levels.append(item_confidence)

    # ── Build item record ────────────────────────────────────────────────────
    item_record = {
        'component_ref': ref,
        'material_name': material_name,
        'gross_weight_g': round(gross_weight_g, 2) if gross_weight_g is not None else None,
        'unit_price_eur_kg': unit_price_eur_kg,
        'cost_per_piece_eur': cost_per_piece_eur,
        'cost_source': cost_source,
        'confidence': item_confidence
    }
    items.append(item_record)
```

---

### Step 4: Calculate summary totals

```python
log.step("Step 4: Calculate summary totals")

make_items = [i for i in items if i['cost_source'] == 'calculated']
buy_items = [i for i in items if i['cost_source'] in ('catalog', 'estimated')]

make_material_cost_eur = round(sum(
    i['cost_per_piece_eur'] for i in make_items if i['cost_per_piece_eur'] is not None
), 4)

buy_material_cost_eur = round(sum(
    i['cost_per_piece_eur'] for i in buy_items if i['cost_per_piece_eur'] is not None
), 4)

total_material_cost_eur = round(make_material_cost_eur + buy_material_cost_eur, 4)

log.info(f"Make material cost:  {make_material_cost_eur} EUR ({len(make_items)} items)")
log.info(f"Buy material cost:   {buy_material_cost_eur} EUR ({len(buy_items)} items)")
log.info(f"Total material cost: {total_material_cost_eur} EUR")
log.info(f"Items with cost: {sum(1 for i in items if i['cost_per_piece_eur'] is not None)}/{len(items)}")
```

---

### Step 5: Determine confidence floor

```python
log.step("Step 5: Determine confidence floor")

CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
if confidence_levels:
    worst = max(confidence_levels, key=lambda c: CONFIDENCE_ORDER.get(c, 5))
else:
    worst = 'S5'

confidence_floor = worst
log.info(f"confidence_floor: {confidence_floor}")
log.info(f"gaps: {len(gaps)} ({sum(1 for g in gaps if g['severity']=='error')} error, {sum(1 for g in gaps if g['severity']=='warning')} warning)")
```

---

### Step 6: Write artifact

```python
log.step("Step 6: Write artifact")

artifact = {
    'node': 'n11',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'items': items,
        'total_material_cost_eur': total_material_cost_eur,
        'make_material_cost_eur': make_material_cost_eur,
        'buy_material_cost_eur': buy_material_cost_eur
    }
}
store.write('n11', artifact)
```

### Step 7: Close log

```python
log.done(artifact)
```

### Step 8: Write report

```python
from reporter import NodeReport

# AI fills this based on actual execution — all four subsections are mandatory
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `artifacts/n05-output.json` | material selections with unit prices (EUR/kg) |
| — | `artifacts/n06-output.json` | quantity calc with gross weights per component |
| — | `artifacts/n08-output.json` | process route operations (secondary — scrap context) |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n11')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n11",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S3",
  "gaps": [
    {
      "rule": "R-11-01",
      "msg": "COMP-XX: missing material unit price (EUR/kg) — cannot calculate cost",
      "severity": "warning"
    },
    {
      "rule": "R-11-02",
      "msg": "COMP-YY: missing gross weight — using estimate if available",
      "severity": "warning"
    }
  ],
  "assumptions": [
    {
      "id": "A-COMP-YY-gross-weight",
      "field": "COMP-YY.gross_weight_g",
      "value": "15.40",
      "unit": "g",
      "confidence": "S4",
      "rationale": "gross_weight estimated from net_weight × 1.10 (10% scrap assumption)"
    }
  ],
  "payload": {
    "items": [
      {
        "component_ref": "COMP-01",
        "material_name": "PA12",
        "gross_weight_g": 14.40,
        "unit_price_eur_kg": 8.50,
        "cost_per_piece_eur": 0.1224,
        "cost_source": "calculated",
        "confidence": "S2"
      },
      {
        "component_ref": "COMP-02",
        "material_name": "",
        "gross_weight_g": null,
        "unit_price_eur_kg": null,
        "cost_per_piece_eur": 3.50,
        "cost_source": "catalog",
        "confidence": "S4"
      }
    ],
    "total_material_cost_eur": 3.6224,
    "make_material_cost_eur": 0.1224,
    "buy_material_cost_eur": 3.50
  }
}
```

---

## Calculation Reference

### Material cost formulas by item type

| Type | Formula | Inputs needed |
|------|---------|---------------|
| `make` | `gross_weight_kg × unit_price_eur_kg` | gross_weight_g (from n06), unit_price_eur_kg (from n05) |
| `buy` | catalog or estimated price per piece | catalog_price_eur or buy_price_eur (from n05) |

Where: `gross_weight_kg = gross_weight_g / 1000`

### Summary totals

```
make_material_cost_eur = SUM(cost_per_piece_eur) for all make items
buy_material_cost_eur  = SUM(cost_per_piece_eur) for all buy items
total_material_cost_eur = make_material_cost_eur + buy_material_cost_eur
```

### Data flow

```
n05 (Material Selection)  →  unit_price_eur_kg, material_name, price_source
n06 (Quantity Calc)        →  gross_weight_g, net_weight_g
n08 (Process Route)        →  scrap_rate_pct (secondary — for cross-check only)
                               ↓
n11 calculates: cost_per_piece_eur = gross_weight_kg × unit_price_eur_kg
                               ↓
n16 (RC) consumes total_material_cost_eur
```

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-11-01 | Item missing material unit price (EUR/kg) in n05 | warning | Cannot calculate cost for that item; item remains in list with `cost_per_piece_eur: null` |
| R-11-02 | Item missing gross weight from n06 | warning | Attempt fallback: `net_weight × 1.10` (10% scrap assumption, S4); if no net_weight either, `cost_per_piece_eur: null` |

---

## Optimize Mode

When the user provides more precise data (replacing S4/S5 assumptions with S1/S2 measured values):

1. Read existing `artifacts/n11-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which fields are updated (compare new data vs existing assumptions):
   - Updated material prices from supplier quote (S4 -> S1): recalculate affected items
   - Updated gross weights from n06 re-run: recalculate affected items
   - Resolved R-11-01 gap (price now available): calculate previously missing cost
   - Resolved R-11-02 gap (weight now available): calculate previously missing cost
4. Only update affected items; preserve unchanged items
5. Recalculate summary totals and `confidence_floor` (may improve from S4 to S1/S2)
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 6/7/8)
8. Run Validation

### When to fall back to Build mode

- BOM items added or removed (n05/n06 item lists changed structure) -> full recalculation needed
- Upstream payload structure changed (new/deleted fields in n05 or n06)
- `confidence_floor` degraded from S1/S2 to S4/S5 (data quality regression)

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n11-output.json`
2. Run Validation below
3. Summarize: gaps count (by severity), assumptions count, confidence_floor
4. Check: are all n05/n06 component refs represented in items list?
5. Cross-check: `total_material_cost_eur == make_material_cost_eur + buy_material_cost_eur`
6. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n11')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
items = p.get('items', [])
assert len(items) > 0, "items list is empty — no components costed"

# Summary totals must be non-negative
assert p.get('total_material_cost_eur', -1) >= 0, \
    "total_material_cost_eur must be >= 0"
assert p.get('make_material_cost_eur', -1) >= 0, \
    "make_material_cost_eur must be >= 0"
assert p.get('buy_material_cost_eur', -1) >= 0, \
    "buy_material_cost_eur must be >= 0"

# Totals must add up
expected_total = round(p.get('make_material_cost_eur', 0) + p.get('buy_material_cost_eur', 0), 4)
actual_total = p.get('total_material_cost_eur', 0)
assert abs(actual_total - expected_total) < 0.01, \
    f"total_material_cost_eur ({actual_total}) != make + buy ({expected_total})"

# Per-item validation
for item in items:
    ref = item.get('component_ref', '?')

    # If cost exists, must be positive
    if item.get('cost_per_piece_eur') is not None:
        assert item['cost_per_piece_eur'] > 0, \
            f"{ref}: cost_per_piece_eur must be > 0 (got {item['cost_per_piece_eur']})"

    # cost_source must be valid
    assert item.get('cost_source') in ('calculated', 'catalog', 'estimated'), \
        f"{ref}: cost_source must be calculated/catalog/estimated (got {item.get('cost_source')})"

    # For calculated items: must have weight and price
    if item.get('cost_source') == 'calculated' and item.get('cost_per_piece_eur') is not None:
        assert item.get('gross_weight_g') is not None and item.get('gross_weight_g') > 0, \
            f"{ref}: calculated item must have gross_weight_g > 0"
        assert item.get('unit_price_eur_kg') is not None and item.get('unit_price_eur_kg') > 0, \
            f"{ref}: calculated item must have unit_price_eur_kg > 0"

# 3. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

# 4. Cross-check: items count vs upstream
n05 = store.read('n05')
n06 = store.read('n06')
if n05:
    n05_count = len(n05.get('payload', {}).get('items', []))
    n11_count = len(items)
    if n11_count < n05_count:
        print(f"⚠ n11 has {n11_count} items but n05 has {n05_count} — some may be missing")

print(f"✓ n11 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Items: {len(items)} ({sum(1 for i in items if i.get('cost_per_piece_eur'))} with cost)")
print(f"  Total material cost: {p['total_material_cost_eur']} EUR")
print(f"    Make: {p['make_material_cost_eur']} EUR")
print(f"    Buy:  {p['buy_material_cost_eur']} EUR")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
