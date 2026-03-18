# NODE-06: Quantity Calc（用量计算）

**Purpose**: Calculate material quantities (net weight, gross weight, scrap rate, annual consumption) for each BOM item.
**Input**: `artifacts/n03-output.json` (component dimensions), `artifacts/n04-output.json` (BOM structure), `artifacts/n01-output.json` (annual_volume)
**Output**: `artifacts/n06-output.json`
**Type**: auto (pure mathematical calculation, no human input needed)

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

# n06 upstream edges (from network.json):
#   n03 → n06 (normal)   — component tree with dimensions
#   n04 → n06 (secondary) — BOM with item numbers and materials
upstream_ids = ['n03', 'n04']
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

# Also read n01 for annual_volume (not a direct upstream edge, but needed for consumption calc)
n01 = store.read('n01')
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 未完成 (status={n01['status'] if n01 else 'missing'})"

log = NodeLogger('<project_path>', 'n06')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
log.info(f"n01: status={store.get_status('n01')}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input data

```python
log.step("Step 1: Read input data from n01, n03, n04")

n01_payload = n01['payload']
n03 = store.read('n03')
n04 = store.read('n04')
n03_payload = n03['payload']
n04_payload = n04['payload']

# ── From n01: annual volume ──────────────────────────────────────────────────
annual_volume = n01_payload.get('annual_volume')
annual_volume_confidence = 'S1'

# Check if annual_volume is an assumption (R-01-01 gap present)
n01_gap_rules = [g['rule'] for g in n01.get('gaps', [])]
if 'R-01-01' in n01_gap_rules or annual_volume is None:
    # Use assumption value from n01 gap or default
    if annual_volume is None:
        annual_volume = 50000  # S4 industry default
    annual_volume_confidence = 'S4'
    log.warn(f"annual_volume={annual_volume} is assumption (S4)")

# ── From n03: component tree with dimensions ────────────────────────────────
components = n03_payload.get('components', [])
log.info(f"n03 components: {len(components)}")

# ── From n04: BOM items with materials ───────────────────────────────────────
bom_items = n04_payload.get('items', [])
log.info(f"n04 BOM items: {len(bom_items)}")
log.info(f"annual_volume: {annual_volume} (confidence: {annual_volume_confidence})")
```

---

### Step 2: Build material density lookup

```python
log.step("Step 2: Build material density lookup")

# Common material densities (g/cm³) — S3 company experience data
DENSITY_TABLE = {
    # Metals
    'steel':        7.85,
    'stainless_steel': 7.93,
    'carbon_steel': 7.85,
    'aluminum':     2.70,
    'brass':        8.50,
    'copper':       8.96,
    'zinc':         7.13,
    # Polymers
    'pa6':          1.13,
    'pa66':         1.14,
    'pa11':         1.04,
    'pa12':         1.02,
    'pom':          1.41,
    'pp':           0.91,
    'pe':           0.95,
    'hdpe':         0.96,
    'pvdf':         1.78,
    'ptfe':         2.15,
    'pps':          1.35,
    'tpe':          1.10,
    'epdm':         1.15,
    'nbr':          1.20,
    'fkm':          1.80,
    'silicone':     1.15,
    # Rubber
    'rubber':       1.20,
    'natural_rubber': 0.92,
}

def get_density(material_key: str) -> float:
    """
    Look up density by material key (case-insensitive, fuzzy).
    Returns density in g/cm³ or None if not found.
    """
    key = material_key.lower().replace(' ', '_').replace('-', '_')
    if key in DENSITY_TABLE:
        return DENSITY_TABLE[key]
    # Fuzzy: check if any key is a substring
    for k, v in DENSITY_TABLE.items():
        if k in key or key in k:
            return v
    return None

log.info(f"Density table: {len(DENSITY_TABLE)} materials loaded")
```

---

### Step 3: Calculate net weight for each component

```python
log.step("Step 3: Calculate net weight per component")

# Default scrap rates by process type (S3, company experience)
SCRAP_DEFAULTS = {
    'extrusion':        0.065,   # 5-8%, use midpoint 6.5%
    'injection_molding': 0.035,  # 2-5%, use midpoint 3.5%
    'cnc_machining':    0.15,    # 10-20%, use midpoint 15%
    'stamping':         0.115,   # 8-15%, use midpoint 11.5%
    'forming':          0.115,   # 8-15%, use midpoint 11.5%
    'assembly':         0.0,     # no material scrap
    'cut_to_length':    0.04,    # 3-5%, use midpoint 4%
    'welding':          0.02,    # minor filler loss
    'bending':          0.03,    # minor stretch loss
}

def calc_net_weight_tube(od_mm, id_mm, length_mm, density_g_cm3):
    """
    Tube/pipe: net_weight = π × (OD² - ID²) / 4 × length × density
    All dimensions in mm, density in g/cm³.
    Returns weight in grams.
    """
    # Convert mm to cm for density compatibility
    od_cm = od_mm / 10.0
    id_cm = id_mm / 10.0
    length_cm = length_mm / 10.0
    volume_cm3 = math.pi * (od_cm**2 - id_cm**2) / 4.0 * length_cm
    return volume_cm3 * density_g_cm3

def calc_net_weight_plate(length_mm, width_mm, thickness_mm, density_g_cm3):
    """
    Plate/sheet: net_weight = length × width × thickness × density
    All dimensions in mm, density in g/cm³.
    Returns weight in grams.
    """
    volume_cm3 = (length_mm / 10.0) * (width_mm / 10.0) * (thickness_mm / 10.0)
    return volume_cm3 * density_g_cm3

def calc_net_weight_molded(volume_cm3, density_g_cm3):
    """
    Molded part: net_weight = estimated volume × density.
    If volume not available, use material_hint weight directly.
    Returns weight in grams.
    """
    return volume_cm3 * density_g_cm3

def get_scrap_rate(process_type: str) -> float:
    """
    Look up default scrap rate by process type.
    Returns decimal (e.g. 0.065 for 6.5%).
    """
    key = process_type.lower().replace(' ', '_').replace('-', '_')
    if key in SCRAP_DEFAULTS:
        return SCRAP_DEFAULTS[key]
    for k, v in SCRAP_DEFAULTS.items():
        if k in key or key in k:
            return v
    return 0.05  # fallback default 5%
```

---

### Step 4: Iterate BOM items and compute quantities

```python
log.step("Step 4: Calculate quantities for each BOM item")

items = []
gaps = []
assumptions = []
confidence_levels = []

for bom_item in bom_items:
    item_number = bom_item.get('item_number', '')
    component_ref = bom_item.get('component_ref', '')
    material_key = bom_item.get('material', '')
    component_type = bom_item.get('component_type', '')  # tube, plate, molded_part, buy_part
    process_type = bom_item.get('process', '')

    # ── Find matching n03 component for dimensions ───────────────────────────
    comp = None
    for c in components:
        if c.get('id') == component_ref:
            comp = c
            break

    # ── Determine density ────────────────────────────────────────────────────
    density = get_density(material_key)
    density_confidence = 'S3'
    if density is None:
        # Try from n04 material_hint or n03 material data
        hint_density = bom_item.get('density_g_cm3')
        if hint_density:
            density = hint_density
            density_confidence = 'S2'
        else:
            density = 1.0  # fallback — flag as assumption
            density_confidence = 'S5'
            assumptions.append({
                'id': f'A-{component_ref}-density',
                'field': f'{component_ref}.density',
                'value': str(density),
                'unit': 'g/cm³',
                'confidence': 'S5',
                'rationale': f'Material "{material_key}" not in density table, using 1.0 g/cm³ placeholder'
            })
            log.warn(f"{component_ref}: unknown material '{material_key}', density=1.0 (S5)")

    # ── Calculate net weight by component type ───────────────────────────────
    net_weight_g = None
    calc_method = ''
    item_confidence = 'S2'

    if component_type in ('tube', 'pipe'):
        dims = comp.get('dimensions', {}) if comp else {}
        od = dims.get('od_mm') or dims.get('outer_diameter_mm')
        id_ = dims.get('id_mm') or dims.get('inner_diameter_mm')
        length = dims.get('length_mm')
        if od and id_ and length:
            net_weight_g = calc_net_weight_tube(od, id_, length, density)
            calc_method = f"tube: π×(OD²-ID²)/4×L×ρ  [OD={od}, ID={id_}, L={length}, ρ={density}]"
        else:
            gaps.append({
                'rule': 'R-06-02',
                'msg': f'{component_ref}: missing tube dimensions (od/id/length) — cannot calculate net weight',
                'severity': 'warning'
            })
            log.warn(f"{component_ref}: missing tube dimensions for weight calc")

    elif component_type in ('plate', 'sheet'):
        dims = comp.get('dimensions', {}) if comp else {}
        length = dims.get('length_mm')
        width = dims.get('width_mm')
        thickness = dims.get('thickness_mm')
        if length and width and thickness:
            net_weight_g = calc_net_weight_plate(length, width, thickness, density)
            calc_method = f"plate: L×W×T×ρ  [L={length}, W={width}, T={thickness}, ρ={density}]"
        else:
            gaps.append({
                'rule': 'R-06-02',
                'msg': f'{component_ref}: missing plate dimensions (length/width/thickness) — cannot calculate net weight',
                'severity': 'warning'
            })
            log.warn(f"{component_ref}: missing plate dimensions for weight calc")

    elif component_type == 'molded_part':
        dims = comp.get('dimensions', {}) if comp else {}
        volume = dims.get('volume_cm3')
        hint_weight = bom_item.get('weight_g') or (comp.get('weight_g') if comp else None)
        if volume:
            net_weight_g = calc_net_weight_molded(volume, density)
            calc_method = f"molded: V×ρ  [V={volume} cm³, ρ={density}]"
        elif hint_weight:
            net_weight_g = hint_weight
            calc_method = f"molded: material_hint weight={hint_weight}g"
            item_confidence = 'S4'
        else:
            gaps.append({
                'rule': 'R-06-02',
                'msg': f'{component_ref}: molded part missing volume and weight hint — cannot calculate',
                'severity': 'warning'
            })
            log.warn(f"{component_ref}: molded part — no volume or weight hint")

    elif component_type == 'buy_part':
        catalog_weight = bom_item.get('weight_g') or (comp.get('weight_g') if comp else None)
        if catalog_weight:
            net_weight_g = catalog_weight
            calc_method = f"buy_part: catalog weight={catalog_weight}g"
            item_confidence = 'S4'
        else:
            # Estimate from similar parts — flag as assumption
            net_weight_g = bom_item.get('estimated_weight_g')
            if net_weight_g:
                calc_method = f"buy_part: estimated from similar parts={net_weight_g}g"
                item_confidence = 'S4'
                assumptions.append({
                    'id': f'A-{component_ref}-weight',
                    'field': f'{component_ref}.net_weight_g',
                    'value': str(net_weight_g),
                    'unit': 'g',
                    'confidence': 'S4',
                    'rationale': f'Buy part weight estimated from similar parts catalog'
                })
            else:
                gaps.append({
                    'rule': 'R-06-02',
                    'msg': f'{component_ref}: buy part missing catalog weight and no estimate available',
                    'severity': 'warning'
                })
                log.warn(f"{component_ref}: buy part — no weight data")

    else:
        # Unknown component type — try generic volume × density if dimensions available
        dims = comp.get('dimensions', {}) if comp else {}
        hint_weight = bom_item.get('weight_g') or (comp.get('weight_g') if comp else None)
        if hint_weight:
            net_weight_g = hint_weight
            calc_method = f"generic: hint weight={hint_weight}g"
            item_confidence = 'S4'
        else:
            gaps.append({
                'rule': 'R-06-02',
                'msg': f'{component_ref}: unknown component_type "{component_type}" and no weight hint',
                'severity': 'warning'
            })
            log.warn(f"{component_ref}: unknown type '{component_type}', no weight data")

    # ── Scrap rate ───────────────────────────────────────────────────────────
    scrap_rate = get_scrap_rate(process_type) if process_type else 0.05
    scrap_rate_pct = round(scrap_rate * 100, 1)
    scrap_source = f"{process_type} default ({SCRAP_DEFAULTS.get(process_type.lower().replace(' ','_').replace('-','_'), 'fallback 5%')*100:.0f}%)" if process_type else "fallback 5%"

    # If multiple processes apply, sum scrap rates (e.g. extrusion + cut)
    # This should be customized per BOM item if process chain is known from n04
    process_chain = bom_item.get('process_chain', [])
    if len(process_chain) > 1:
        combined_scrap = 0
        scrap_parts = []
        for proc in process_chain:
            rate = get_scrap_rate(proc)
            combined_scrap += rate
            scrap_parts.append(f"{proc} {rate*100:.0f}%")
        scrap_rate = min(combined_scrap, 0.50)  # cap at 50%
        scrap_rate_pct = round(scrap_rate * 100, 1)
        scrap_source = ' + '.join(scrap_parts)

    # ── Gross weight and annual consumption ──────────────────────────────────
    gross_weight_g = None
    annual_net_kg = None
    annual_gross_kg = None

    if net_weight_g is not None:
        gross_weight_g = round(net_weight_g * (1 + scrap_rate), 2)
        annual_net_kg = round(net_weight_g * annual_volume / 1000, 1)
        annual_gross_kg = round(gross_weight_g * annual_volume / 1000, 1)
        net_weight_g = round(net_weight_g, 2)

    # ── Determine item confidence ────────────────────────────────────────────
    # Downgrade confidence if density or weight was assumed
    if density_confidence in ('S4', 'S5'):
        item_confidence = density_confidence
    confidence_levels.append(item_confidence if net_weight_g else 'S5')

    # ── Build item record ────────────────────────────────────────────────────
    item_record = {
        'component_ref': component_ref,
        'bom_item_number': item_number,
        'net_weight_g': net_weight_g,
        'scrap_rate_pct': scrap_rate_pct,
        'scrap_source': scrap_source,
        'gross_weight_g': gross_weight_g,
        'annual_net_kg': annual_net_kg,
        'annual_gross_kg': annual_gross_kg,
        'calculation_method': calc_method,
        'confidence': item_confidence if net_weight_g else 'S5'
    }
    items.append(item_record)
    log.info(f"{component_ref}: net={net_weight_g}g, scrap={scrap_rate_pct}%, gross={gross_weight_g}g, method={calc_method}")

# ── Assembly totals ──────────────────────────────────────────────────────────
total_net = round(sum(i['net_weight_g'] for i in items if i['net_weight_g']), 2)
total_gross = round(sum(i['gross_weight_g'] for i in items if i['gross_weight_g']), 2)

log.info(f"Total assembly: net={total_net}g, gross={total_gross}g")
log.info(f"Items calculated: {sum(1 for i in items if i['net_weight_g'])}/{len(items)}")
```

---

### Step 5: Determine gaps and confidence floor

```python
log.step("Step 5: Determine gaps and confidence floor")

# R-06-01: annual_volume is assumption (inherited from n01)
if annual_volume_confidence != 'S1':
    gaps.append({
        'rule': 'R-06-01',
        'msg': f'annual_volume={annual_volume} is assumption (inherited from n01 R-01-01)',
        'severity': 'warning',
        'assumption': f'annual_volume={annual_volume} ({annual_volume_confidence})'
    })
    assumptions.append({
        'id': 'A-annual-volume',
        'field': 'annual_volume',
        'value': str(annual_volume),
        'unit': '件/年',
        'confidence': annual_volume_confidence,
        'rationale': 'Inherited from n01 — customer RFQ did not specify annual volume'
    })

# R-06-02 gaps already added in Step 4 loop for missing dimensions

# Confidence floor = lowest among all items
CONFIDENCE_ORDER = {'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4, 'S5': 5}
if confidence_levels:
    worst = max(confidence_levels, key=lambda c: CONFIDENCE_ORDER.get(c, 5))
else:
    worst = 'S5'

# Also factor in annual_volume confidence
if CONFIDENCE_ORDER.get(annual_volume_confidence, 5) > CONFIDENCE_ORDER.get(worst, 5):
    worst = annual_volume_confidence

confidence_floor = worst
log.info(f"confidence_floor: {confidence_floor}")
log.info(f"gaps: {len(gaps)} ({sum(1 for g in gaps if g['severity']=='error')} error, {sum(1 for g in gaps if g['severity']=='warning')} warning)")
```

---

### Step 6: Write artifact

```python
log.step("Step 6: Write artifact")

artifact = {
    'node': 'n06',
    'project': '<project_id>',
    'status': 'ready',
    'produced_at': datetime.now(timezone.utc).isoformat(),
    'confidence_floor': confidence_floor,
    'gaps': gaps,
    'assumptions': assumptions,
    'payload': {
        'annual_volume': annual_volume,
        'annual_volume_confidence': annual_volume_confidence,
        'items': items,
        'total_assembly_net_weight_g': total_net,
        'total_assembly_gross_weight_g': total_gross
    }
}
store.write('n06', artifact)
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
| — | `artifacts/n01-output.json` | annual_volume, gap R-01-01 status |
| — | `artifacts/n03-output.json` | component tree with dimensions |
| — | `artifacts/n04-output.json` | BOM items with materials and processes |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'n06')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Output Schema

```json
{
  "node": "n06",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S2",
  "gaps": [
    {
      "rule": "R-06-01",
      "msg": "annual_volume=50000 is assumption (inherited from n01 R-01-01)",
      "severity": "warning",
      "assumption": "annual_volume=50000 (S4)"
    },
    {
      "rule": "R-06-02",
      "msg": "COMP-XX: missing tube dimensions (od/id/length) — cannot calculate net weight",
      "severity": "warning"
    }
  ],
  "assumptions": [
    {
      "id": "A-annual-volume",
      "field": "annual_volume",
      "value": "50000",
      "unit": "件/年",
      "confidence": "S4",
      "rationale": "Inherited from n01 — customer RFQ did not specify annual volume"
    }
  ],
  "payload": {
    "annual_volume": 50000,
    "annual_volume_confidence": "S4",
    "items": [
      {
        "component_ref": "COMP-01",
        "bom_item_number": "...",
        "net_weight_g": 13.46,
        "scrap_rate_pct": 7,
        "scrap_source": "extrusion 5% + cut 2%",
        "gross_weight_g": 14.4,
        "annual_net_kg": 673,
        "annual_gross_kg": 720,
        "calculation_method": "tube: π×(OD²-ID²)/4×L×ρ",
        "confidence": "S2"
      }
    ],
    "total_assembly_net_weight_g": 0,
    "total_assembly_gross_weight_g": 0
  }
}
```

---

## Calculation Reference

### Net weight formulas by component type

| Type | Formula | Dimensions needed |
|------|---------|-------------------|
| `tube` / `pipe` | `π × (OD² - ID²) / 4 × length × density` | od_mm, id_mm, length_mm |
| `plate` / `sheet` | `length × width × thickness × density` | length_mm, width_mm, thickness_mm |
| `molded_part` | `volume × density` (or use material_hint weight) | volume_cm3 (or weight_g hint) |
| `buy_part` | Catalog weight or estimate from similar parts (S4) | weight_g from catalog |

All dimensions in mm; density in g/cm3; output weight in grams.

For ALL types: `gross_weight = net_weight × (1 + scrap_rate)`

### Scrap rate defaults (S3, company experience)

| Process | Range | Default (midpoint) |
|---------|-------|-------------------|
| Extrusion | 5-8% | 6.5% |
| Injection molding | 2-5% | 3.5% |
| CNC machining | 10-20% | 15% |
| Stamping / forming | 8-15% | 11.5% |
| Assembly (no material scrap) | 0% | 0% |
| Cut to length | 3-5% | 4% |

For multi-process chains (e.g. extrusion + cut to length), sum individual scrap rates. Cap total scrap at 50%.

### Annual consumption

```
annual_net_kg  = net_weight_g  × annual_volume / 1000
annual_gross_kg = gross_weight_g × annual_volume / 1000
```

`annual_volume` is inherited from n01. If n01 has gap R-01-01 (annual_volume is S4 assumption), propagate as R-06-01 warning.

---

## Gap Rules

| Rule | Condition | Severity | Action |
|------|-----------|----------|--------|
| R-06-01 | `annual_volume` is assumption (inherited from n01 R-01-01) | warning | Propagate assumption; downstream n11 will inherit |
| R-06-02 | Component missing dimensions needed for weight calculation | warning | Per-component; log which dimensions are missing |

---

## Optimize Mode

When the user provides more precise data (replacing S4/S5 assumptions with S1/S2 measured values):

1. Read existing `artifacts/n06-output.json`
2. Initialize logger; all step titles prefixed with `[Optimize]`
3. Identify which fields are updated (compare new data vs existing assumptions):
   - Updated `annual_volume` from customer (S4 -> S1): recalculate all annual consumption
   - Updated component dimensions from 3D model (n03 re-run): recalculate affected net weights
   - Updated scrap rates from production data: replace defaults with actuals
   - Updated material density from datasheet: recalculate affected weights
4. Only update affected items; preserve unchanged items
5. Recalculate `confidence_floor` (may improve from S4 to S1/S2)
6. Remove resolved entries from `gaps` and `assumptions`
7. Write artifact -> close log -> write report (same as Build Steps 6/7/8)
8. Run Validation

### When to fall back to Build mode

- BOM items added or removed (n04 changed structure) -> full recalculation needed
- Component tree restructured (n03 changed) -> full recalculation needed
- `confidence_floor` degraded from S1/S2 to S4/S5 (data quality regression)

If uncertain, choose Build — full recalculation is safer than partial update.

---

## Review Mode

Check existing artifact quality only, no file modifications:

1. Read `artifacts/n06-output.json`
2. Run Validation below
3. Summarize: gaps count (by severity), assumptions count, confidence_floor
4. Check: are all BOM items from n04 represented in items list?
5. Output quality summary, do not write artifact

---

## Validation

```python
# Run after Build/Optimize completes
artifact = store.read('n06')
p = artifact.get('payload', {})

# 1. Required envelope fields
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status invalid"
assert artifact.get('confidence_floor'), "confidence_floor not set"

# 2. Node-specific validation
items = p.get('items', [])
assert len(items) > 0, "items list is empty — no components calculated"

# Total weight must be positive
assert p.get('total_assembly_net_weight_g', 0) > 0, \
    "total_assembly_net_weight_g must be positive"
assert p.get('total_assembly_gross_weight_g', 0) > 0, \
    "total_assembly_gross_weight_g must be positive"

# Gross weight >= net weight
assert p['total_assembly_gross_weight_g'] >= p['total_assembly_net_weight_g'], \
    "total gross weight must be >= total net weight"

# Per-item validation
for item in items:
    ref = item.get('component_ref', '?')

    # All items must have net_weight_g > 0 (or None if dimensions missing — flagged by R-06-02)
    if item.get('net_weight_g') is not None:
        assert item['net_weight_g'] > 0, \
            f"{ref}: net_weight_g must be > 0 (got {item['net_weight_g']})"

    # Scrap rate between 0% and 50%
    scrap = item.get('scrap_rate_pct', 0)
    assert 0 <= scrap <= 50, \
        f"{ref}: scrap_rate_pct must be 0-50% (got {scrap}%)"

    # Gross weight > net weight (if both present)
    if item.get('net_weight_g') and item.get('gross_weight_g'):
        assert item['gross_weight_g'] >= item['net_weight_g'], \
            f"{ref}: gross_weight must be >= net_weight"

    # Must have calculation_method
    assert item.get('calculation_method'), \
        f"{ref}: calculation_method is missing"

# annual_volume must be positive
assert p.get('annual_volume', 0) > 0, "annual_volume must be positive"

# 3. Gap completeness
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

# 4. Cross-check: items count vs n04 BOM count
n04 = store.read('n04')
if n04:
    n04_count = len(n04.get('payload', {}).get('items', []))
    n06_count = len(items)
    if n06_count < n04_count:
        print(f"⚠ n06 has {n06_count} items but n04 has {n04_count} BOM items — some may be missing")

print(f"✓ n06 validation passed — confidence_floor: {artifact['confidence_floor']}")
print(f"  Items: {len(items)} ({sum(1 for i in items if i.get('net_weight_g'))} with weight)")
print(f"  Total net weight:   {p['total_assembly_net_weight_g']}g")
print(f"  Total gross weight: {p['total_assembly_gross_weight_g']}g")
print(f"  Annual volume:      {p['annual_volume']} (confidence: {p['annual_volume_confidence']})")
print(f"  Gaps: {len(artifact.get('gaps', []))}")
```
