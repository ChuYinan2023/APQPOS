# NODE-07: DFMEA（Design Failure Mode and Effects Analysis）

**Purpose**: Analyze each component and assembly interface from n03 for potential failure modes; score severity/occurrence/detection per AIAG DFMEA 4th edition; compute RPN; recommend actions for high-risk items; feed back newly discovered risks to n02.
**Input**: `artifacts/n03-output.json` (components + assembly_interfaces), `artifacts/n02-output.json` (categories with DRG indicators)
**Output**: `artifacts/n07-output.json`
**Type**: mixed（AI generates initial DFMEA rows; engineer reviews and supplements）

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

n03 = store.read('n03')
n02 = store.read('n02')

assert n03 and n03['status'] in ('ready', 'done'), \
    f"n03 status is '{n03['status'] if n03 else 'missing'}' — must be 'ready' or 'done' before running n07"
assert n02 and n02['status'] in ('ready', 'done'), \
    f"n02 status is '{n02['status'] if n02 else 'missing'}' — must be 'ready' or 'done' before running n07"

# Check for error-level gaps in upstream
error_gaps_total = 0
for uid, art in [('n03', n03), ('n02', n02)]:
    error_gaps = [g for g in art.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} has {len(error_gaps)} error gap(s)")

if error_gaps_total:
    print(f"⚠ Upstream has {error_gaps_total} total error gap(s) — n07 results may be unreliable")

# Verify n03 has components
components = n03['payload'].get('components', [])
assert len(components) > 0, "n03 has no components — cannot run DFMEA (R-07-01 error)"

# Start logger
log = NodeLogger('<project_path>', 'n07')
log.step("Precondition: n03 and n02 ready, components present")
log.info(f"n03 confidence_floor: {n03['confidence_floor']}")
log.info(f"n02 confidence_floor: {n02['confidence_floor']}")
log.info(f"n03 component count: {len(components)}")
log.info(f"n03 assembly_interfaces count: {len(n03['payload'].get('assembly_interfaces', []))}")
log.info(f"n03 gaps: {[g['rule'] for g in n03.get('gaps', [])]}")
log.info(f"n02 gaps: {[g['rule'] for g in n02.get('gaps', [])]}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input fields from n03 and n02

```python
log.step("Step 1: Read input fields from n03 and n02")

n03_payload = n03['payload']
n02_payload = n02['payload']

# ── From n03 ──────────────────────────────────────────────────────────────────
components          = n03_payload.get('components', [])
assembly_interfaces = n03_payload.get('assembly_interfaces', [])

# ── From n02: collect ALL indicators across ALL categories ────────────────────
all_indicators = []
categories = n02_payload.get('categories', [])
for cat in categories:
    for ind in cat.get('indicators', []):
        ind['_category_id'] = cat.get('id')
        all_indicators.append(ind)

# ── Collect SC/CC items from n03 components ───────────────────────────────────
# SC/CC may be stored in component special_characteristics or dimension-level sc_cc_ref
sc_cc_items = []
for comp in components:
    for dim in comp.get('dimensions', []):
        if dim.get('sc_cc_ref'):
            sc_cc_items.append({
                'comp_id': comp['id'],
                'comp_name': comp['name'],
                'comp_type': comp['type'],
                'dim_id': dim.get('id'),
                'sc_cc_ref': dim['sc_cc_ref'],
            })
    # Also check component-level special_characteristics if present
    for sc in comp.get('special_characteristics', []):
        sc_cc_items.append({
            'comp_id': comp['id'],
            'comp_name': comp['name'],
            'comp_type': comp['type'],
            'dim_id': None,
            'sc_cc_ref': sc.get('parameter') or sc.get('name'),
        })

log.info(f"components          : {len(components)}")
log.info(f"assembly_interfaces : {len(assembly_interfaces)}")
log.info(f"n02 indicators      : {len(all_indicators)}")
log.info(f"SC/CC items         : {len(sc_cc_items)}")
for comp in components:
    log.info(f"  {comp['id']} ({comp['type']}): {comp['name']}")
for intf in assembly_interfaces:
    log.info(f"  {intf['id']} ({intf['type']}): {intf.get('description', '')[:60]}")
```

---

### Step 2: Define failure mode lookup tables

> **DESIGN RULE** — These tables are GENERIC. The AI selects applicable rows
> based on each component's `type` field from n03. Components whose type does
> not match any predefined category use the `generic` fallback.

```python
log.step("Step 2: Define failure mode lookup tables")

# ── Component-type → failure mode templates ───────────────────────────────────
# Each template: (failure_mode, typical_effect, typical_cause, typical_prevention, typical_detection)
# AI adapts wording to the specific component's function and context.

COMPONENT_FM_TABLE = {
    "tube": [
        ("Burst under pressure",           "Fluid leak → safety risk",         "Material defect or wall thickness below spec",     "Material certification + incoming inspection",         "100% burst/proof test"),
        ("External leak at joint",          "Fluid leak → environmental/safety","Poor joint geometry or surface finish",             "Dimensional control on OD/ID",                          "Leak test (helium or pressure decay)"),
        ("Internal blockage",              "Loss of fluid flow → system failure","Foreign material or internal collapse",             "Cleanliness spec + process control",                   "Flow test at end-of-line"),
        ("Fatigue crack",                  "Progressive leak → field failure",  "Vibration fatigue at bend radius or clamp point",   "FEA validation of bend radius and clamp spacing",      "DV/PV vibration test"),
        ("Excessive deformation",          "Reduced flow or interference",      "Insufficient wall thickness or wrong material",     "Design review of wall thickness vs. pressure",         "Dimensional inspection post-forming"),
        ("Permeation",                     "Emission non-compliance",           "Material incompatible with fluid or temp out of range","Material qualification per fluid compatibility spec",  "Permeation test per applicable standard"),
        ("Corrosion (internal/external)",  "Wall thinning → eventual leak",     "Fluid chemistry or external environment",           "Material selection per corrosion spec",                 "Salt spray or fluid immersion test"),
    ],
    "connector": [
        ("Disconnect in service",          "Fluid leak → safety risk",         "Insufficient retention force or vibration",         "Retention force spec + design verification",            "Pull-off force test"),
        ("Seal failure",                   "Fluid leak at interface",           "O-ring damage, wrong size, or material degradation","Seal design review + material qualification",           "Leak test after assembly"),
        ("Assembly error (misassembly)",   "Undetected leak or pull-apart",     "Operator error or unclear assembly instruction",    "Poka-yoke (keying/color coding) + work instruction",    "Secondary latch verification / visual audit"),
        ("Impact fracture",               "Connector body crack → leak",       "Handling damage or impact in service",              "Material impact resistance spec",                       "Visual inspection + impact test (DV/PV)"),
        ("Latch failure",                  "Undetected incomplete connection",   "Latch spring fatigue or plastic creep",             "Latch force retention spec + material selection",       "Latch engagement force test"),
    ],
    "quick_connector": [
        ("Pull-apart in service",          "Fluid leak → safety risk",         "Insufficient retention or vibration loosening",     "Retention force spec per applicable standard",          "Pull-off force test (100% or sample)"),
        ("Misassembly (incomplete insert)","Undetected leak path",              "Operator fails to achieve full engagement",         "Poka-yoke: audible click + secondary latch",            "Automated latch verification or visual audit"),
        ("Secondary latch bypass",        "Reduced retention safety margin",    "Latch not engaged due to assembly sequence error", "Assembly instruction + color coding",                   "End-of-line latch check"),
    ],
    "seal": [
        ("Aging / hardening",             "Seal leak → fluid loss",            "Material degradation from heat or fluid exposure",  "Material qualification per fluid + temp range",         "Aging test per applicable standard"),
        ("Swell (excessive)",             "Seal extrusion or interference",     "Incompatible material or fluid composition change", "Fluid compatibility test during material selection",    "Dimensional check after fluid exposure test"),
        ("Installation damage",           "Immediate or early leak",            "Incorrect assembly force or sharp edge on mating part","Assembly tool design + edge break spec on housing",  "Leak test after assembly"),
        ("Extrusion under pressure",      "Seal material enters flow path → leak","Gap too large or pressure exceeds seal rating",   "Gap and pressure design review",                        "Pressure cycle test (DV/PV)"),
    ],
    "gasket": [
        ("Aging / hardening",             "Seal leak → fluid loss",            "Material degradation from heat or fluid exposure",  "Material qualification per fluid + temp range",         "Aging test per applicable standard"),
        ("Swell (excessive)",             "Gasket extrusion or interference",   "Incompatible material or fluid composition change", "Fluid compatibility test during material selection",    "Dimensional check after fluid exposure test"),
        ("Installation damage",           "Immediate or early leak",            "Incorrect torque or misalignment during assembly",  "Torque spec + alignment guide in work instruction",     "Leak test after assembly"),
        ("Creep / relaxation",            "Clamping force loss → leak over time","Insufficient bolt load or high temperature",       "Bolt torque spec + gasket material selection",          "Torque audit + leak retest at DV/PV intervals"),
    ],
    "o-ring": [
        ("Aging / hardening",             "Seal leak → fluid loss",            "Material degradation from heat or fluid exposure",  "Material qualification per fluid + temp range",         "Aging test per applicable standard"),
        ("Swell (excessive)",             "Seal extrusion or interference",     "Incompatible material or fluid composition change", "Fluid compatibility test during material selection",    "Dimensional check after fluid exposure test"),
        ("Installation damage",           "Immediate or early leak",            "Nick or cut during assembly; sharp edge on groove", "Edge break spec on groove + assembly tool design",      "Leak test after assembly"),
        ("Extrusion under pressure",      "Seal material enters flow path → leak","Gap too large or pressure exceeds O-ring rating", "Groove design review per O-ring handbook",               "Pressure cycle test (DV/PV)"),
    ],
    "damper": [
        ("Internal leak",                 "Loss of damping → pressure pulsation","Diaphragm or piston seal failure",                "Damper design qualification + seal material selection", "Pressure pulsation test (DV/PV)"),
        ("Loss of damping function",      "NVH complaint or downstream fatigue","Gas charge loss or spring fatigue",                 "Design life calculation + gas charge retention spec",   "Functional test (frequency response)"),
        ("Fatigue crack on housing",      "External leak → fluid loss",         "Pressure cycling beyond design life",               "Fatigue analysis + safety factor",                      "DV/PV pressure cycle endurance test"),
    ],
    "clip": [
        ("Loosening under vibration",     "Component shift → chafing or NVH",  "Insufficient clamp force or resonance",             "Clamp force spec + FEA modal analysis",                 "Vibration test (DV/PV)"),
        ("Fracture",                      "Component unsupported → damage",     "Material fatigue, overtightening, or impact",       "Material selection + torque spec",                      "Visual inspection + vibration endurance test"),
        ("NVH (rattle/buzz)",             "Customer dissatisfaction",           "Clearance between clip and component",              "Interference fit design or rubber isolator",            "NVH test (DV/PV)"),
        ("Corrosion",                     "Reduced clamp force → loosening",    "Environmental exposure without adequate coating",   "Coating spec (e.g., Zn-Ni) per corrosion requirement", "Salt spray test"),
    ],
    "bracket": [
        ("Loosening under vibration",     "Component shift → chafing or NVH",  "Insufficient bolt torque or thread damage",         "Torque spec + thread-locking compound",                 "Torque audit + vibration test"),
        ("Fracture",                      "Component unsupported → damage",     "Fatigue from vibration or overload",                "FEA stress analysis + safety factor",                   "DV/PV vibration endurance test"),
        ("NVH (rattle/buzz)",             "Customer dissatisfaction",           "Resonance at vehicle operating frequencies",        "FEA modal analysis to avoid resonance band",            "NVH test on vehicle"),
        ("Corrosion",                     "Structural weakening → fracture",    "Environmental exposure without adequate coating",   "Coating spec per corrosion requirement",                "Salt spray test"),
    ],
    "mount": [
        ("Loosening under vibration",     "Component shift → interference",     "Insufficient retention or wrong fastener",          "Fastener spec + prevailing torque nut",                 "Vibration endurance test"),
        ("Fracture",                      "Component detachment",               "Overload or fatigue",                               "Load analysis + material selection",                    "DV/PV durability test"),
        ("Corrosion",                     "Reduced load capacity",              "Environmental exposure",                            "Coating spec per environment requirement",              "Salt spray test"),
    ],
    "protection": [
        ("Missing after assembly",        "Exposed component → damage risk",    "Omitted during assembly or fell off",               "Assembly checklist + poka-yoke fixture",                "Visual inspection / end-of-line audit"),
        ("Damage during handling",        "Protection ineffective → component exposed","Handling force exceeds protection rating",    "Handling instruction + packaging spec",                 "Visual inspection at receiving"),
    ],
    "cover": [
        ("Missing after assembly",        "Exposed component → contamination", "Omitted during assembly",                           "Assembly checklist + poka-yoke fixture",                "Visual inspection / end-of-line audit"),
        ("Damage during handling",        "Cover ineffective",                  "Handling force exceeds cover strength",              "Handling instruction + packaging spec",                 "Visual inspection"),
    ],
    "cap": [
        ("Missing after assembly",        "Open port → contamination or leak",  "Omitted during assembly",                           "Assembly checklist",                                    "Visual inspection / end-of-line audit"),
        ("Damage during handling",        "Cap ineffective",                    "Handling force or chemical attack",                  "Material selection + handling instruction",             "Visual inspection"),
    ],
    "electrical": [
        ("Open circuit",                  "Signal loss → system fault code",    "Wire break, connector corrosion, or solder failure","Wire routing + connector sealing spec",                 "End-of-line electrical continuity test"),
        ("Short circuit",                 "Erroneous signal → incorrect system response","Chafing, water ingress, or insulation failure","Wire routing + grommet/conduit protection",          "Insulation resistance test"),
        ("Signal drift",                  "Inaccurate reading → performance issue","Sensor degradation or EMC interference",          "Sensor qualification + EMC shielding spec",             "Calibration check at DV/PV"),
    ],
    "sensor": [
        ("Open circuit",                  "Signal loss → system fault code",    "Connector corrosion or internal failure",           "Connector sealing spec + material selection",           "End-of-line electrical test"),
        ("Short circuit",                 "Erroneous signal → system fault",    "Water ingress or insulation failure",               "IP rating spec + wire routing",                         "Insulation resistance test"),
        ("Signal drift",                  "Inaccurate measurement",             "Sensor element degradation over time/temp",         "Sensor qualification per operating range",              "Calibration/accuracy test at DV/PV"),
    ],
}

# ── Interface-type → failure mode templates ───────────────────────────────────
INTERFACE_FM_TABLE = {
    "quick_connect": [
        ("Pull-apart",                    "Fluid leak → safety risk",          "Insufficient retention or vibration",               "Retention force spec + secondary latch",                "Pull-off force test"),
        ("Misassembly",                   "Incomplete connection → leak",       "Operator error, no audible click feedback",         "Poka-yoke design + assembly work instruction",          "Automated latch verification"),
        ("Secondary latch bypass",        "Reduced safety margin",              "Assembly sequence error",                           "Color coding + assembly instruction",                   "Visual audit / end-of-line check"),
    ],
    "press_fit": [
        ("Loosening under vibration",     "Joint separation → leak or NVH",    "Interference too low or vibration exceeds design",  "Interference fit tolerance spec + FEA",                 "Push-out force test + vibration test"),
        ("Seal degradation at interface", "Leak at press-fit zone",             "Fretting corrosion or thermal cycling",             "Surface finish spec + material compatibility",          "Leak test after thermal cycling (DV/PV)"),
    ],
    "crimp": [
        ("Loosening under vibration",     "Joint separation → leak",           "Crimp force below spec or die wear",                "Crimp force monitoring + die maintenance schedule",     "Crimp diameter measurement + pull test"),
        ("Seal degradation at interface", "Leak at crimp zone",                 "Ferrule damage or hose surface defect",             "Incoming inspection of hose + ferrule",                 "Leak test after crimp"),
    ],
    "weld": [
        ("Crack in weld zone",           "Structural failure → leak",          "Weld parameter deviation or contamination",         "Weld procedure spec (WPS) + operator qualification",   "Visual + NDT (X-ray or ultrasonic)"),
        ("Porosity",                      "Reduced weld strength → eventual failure","Gas entrapment during welding",                "Shielding gas spec + pre-weld cleaning",                "X-ray or cross-section metallography"),
        ("Incomplete fusion",             "Weak joint → early failure",         "Insufficient heat input or misalignment",           "Weld parameter monitoring + fixture alignment",         "Destructive test (cross-section) on sample"),
    ],
    "braze": [
        ("Crack in braze zone",          "Structural failure → leak",          "Braze parameter deviation or flux residue",         "Braze procedure spec + operator qualification",        "Visual + leak test + cross-section sample"),
        ("Porosity",                      "Reduced joint strength",             "Flux entrapment or improper gap",                   "Gap control + flux application spec",                   "X-ray or cross-section metallography"),
        ("Incomplete fusion",             "Weak joint",                         "Insufficient temperature or filler flow",           "Temperature monitoring + joint design review",          "Destructive test on sample"),
    ],
    "clip_mount": [
        ("Vibration loosening",          "Component shift → chafing or NVH",   "Insufficient retention force",                      "Retention force spec + vibration analysis",             "Vibration endurance test (DV/PV)"),
        ("Resonance",                    "Fatigue failure of clip or component","Natural frequency within vehicle excitation band",   "FEA modal analysis",                                    "NVH test / frequency sweep"),
    ],
    "seal_interface": [
        ("Leak path at interface",       "Fluid leak → safety or emission",    "Surface finish or flatness out of spec",            "Surface finish spec on mating surfaces",                "Leak test after assembly"),
        ("O-ring / gasket damage during assembly","Immediate or early leak",   "Sharp edge, misalignment, or excessive force",      "Edge break spec + assembly tool design",                "Leak test after assembly"),
    ],
    "threaded": [
        ("Loosening under vibration",    "Joint separation → leak or detachment","Insufficient torque or no thread locking",        "Torque spec + thread-locking compound/prevailing nut",  "Torque audit"),
        ("Cross-threading",              "Damaged thread → reduced clamp force","Misalignment during assembly",                      "Thread lead-in chamfer + assembly instruction",         "Torque monitoring (torque-angle)"),
        ("Galling",                      "Seized fastener → cannot service",    "Incompatible materials or no lubrication",          "Material pairing spec + lubrication requirement",       "Torque audit"),
    ],
}

log.info(f"Component FM table: {len(COMPONENT_FM_TABLE)} types defined")
log.info(f"Interface FM table: {len(INTERFACE_FM_TABLE)} types defined")
```

---

### Step 3: Generate failure modes for each component

> **PSEUDOCODE** — AI executes this logic inline, adapting wording to the
> specific component's function and context. Do not run this block directly.

```python
log.step("Step 3: Generate failure modes for each component")

# ── Helper: ID generator ─────────────────────────────────────────────────────
_fm_counter = 0
def make_fm_id() -> str:
    global _fm_counter
    _fm_counter += 1
    return f"FM-{_fm_counter:03d}"

# ── Helper: find matching DRG indicator from n02 ─────────────────────────────
def find_drg_indicator(failure_mode_text: str, comp_type: str) -> str | None:
    """
    Search all_indicators for a DRG indicator whose parameter or design_target
    is relevant to this failure mode. Returns indicator ID or None.
    Match by keyword overlap between failure_mode_text and indicator fields.
    """
    keywords = failure_mode_text.lower().split()
    best_match = None
    best_score = 0
    for ind in all_indicators:
        param = (ind.get('parameter', '') or '').lower()
        target = (ind.get('design_target', '') or '').lower()
        score = sum(1 for kw in keywords if kw in param or kw in target)
        if score > best_score:
            best_score = score
            best_match = ind.get('id')
    return best_match if best_score >= 1 else None

# ── Helper: find SC/CC ref for a component ───────────────────────────────────
def find_sc_cc_ref(comp_id: str, failure_mode_text: str) -> str | None:
    """
    Check if any SC/CC item from sc_cc_items matches this component
    and is relevant to the failure mode.
    """
    for sc in sc_cc_items:
        if sc['comp_id'] == comp_id:
            return sc['sc_cc_ref']
    # Also check by keyword in sc_cc_ref
    fm_lower = failure_mode_text.lower()
    for sc in sc_cc_items:
        ref_lower = (sc['sc_cc_ref'] or '').lower()
        if any(kw in fm_lower for kw in ref_lower.split() if len(kw) > 3):
            return sc['sc_cc_ref']
    return None

failure_modes = []
```

```python
# PSEUDOCODE — Component failure mode generation
#
# For each component in components:
#   1. Determine the component type (comp['type']).
#   2. Look up the type in COMPONENT_FM_TABLE.
#      - If type matches exactly → use that entry.
#      - If type is a synonym (e.g., "hose" → "tube", "coupling" → "connector") → map to nearest entry.
#      - If no match → use "generic" fallback (see below).
#   3. For each (failure_mode, effect, cause, prevention, detection) template in the table:
#      a. Derive the component's FUNCTION from its name, type, and context
#         (e.g., "Transport fuel from tank to engine" for a tube,
#          "Retain tube in chassis routing" for a clip).
#      b. Adapt the template wording to the specific component:
#         - Replace generic terms with component-specific terms
#           (e.g., "Fluid leak" → "Fuel leak" if system is fuel, "Coolant leak" if coolant).
#         - Reference the component's actual dimensions/specs from n03 where applicable.
#      c. Score Severity (S) using AIAG rules:
#         - 9-10: safety/regulatory (fire, loss of steering, toxic exposure)
#         - 7-8: vehicle inoperable (no-start, stall, tow-in)
#         - 4-6: reduced performance (drivability, efficiency, NVH)
#         - 1-3: minor annoyance (cosmetic, barely perceptible)
#      d. Score Occurrence (O) based on design maturity:
#         - Check n03 confidence_floor and component-level confidence.
#         - S1/S2 confidence → proven/mature design → O = 1-4
#         - S3/S4 confidence → new design with limited data → O = 5-8
#         - S5 confidence → completely new → O = 7-10
#      e. Score Detection (D) based on current controls:
#         - 1-2: 100% automated test (leak test, pressure proof test, electrical test)
#         - 3-4: SPC with Cpk > 1.67
#         - 5-6: sample testing (DV/PV program)
#         - 7-8: visual inspection only
#         - 9-10: no detection method defined
#      f. Compute RPN = S × O × D.
#      g. Determine action_required: True if RPN > 100 OR S >= 9.
#      h. If action_required, generate recommended_action:
#         - For high S: add redundant control or design change
#         - For high O: improve prevention (material, process, or design)
#         - For high D: add detection method (test, SPC, poka-yoke)
#      i. Link references:
#         - drg_indicator_ref = find_drg_indicator(failure_mode, comp_type)
#         - sc_cc_ref = find_sc_cc_ref(comp_id, failure_mode)
#      j. Set confidence:
#         - "S1" if scoring is based on test data or proven design history
#         - "S2" if scoring is based on engineering judgment with similar precedent
#         - "S3" if scoring is AI-estimated with limited data
#      k. Append to failure_modes list.
#
# "generic" fallback (for unrecognized component types):
#   - Use the component's special_characteristics from n03 to infer failure modes.
#   - For each special_characteristic, create one FM row:
#     failure_mode = f"{characteristic} out of specification"
#     effect = derive from characteristic type (dimensional → fit issue, material → performance)
#     Set confidence = "S3" (limited data for unknown type).

log.info(f"Component failure modes generated: {len(failure_modes)}")
```

---

### Step 4: Generate failure modes for each assembly interface

> **PSEUDOCODE** — AI executes this logic inline.

```python
log.step("Step 4: Generate failure modes for each assembly interface")

# PSEUDOCODE — Interface failure mode generation
#
# For each interface in assembly_interfaces:
#   1. Determine the interface type (intf['type']).
#   2. Look up the type in INTERFACE_FM_TABLE.
#      - If type matches → use that entry.
#      - If no match → generate generic interface failure modes:
#        * "Interface failure" with effect based on interface description
#        * Set confidence = "S3"
#   3. For each (failure_mode, effect, cause, prevention, detection) template:
#      a. Derive FUNCTION from interface description and connected components.
#      b. Adapt wording: replace "Fluid" with system-specific term,
#         reference actual component IDs from intf['from_comp'] and intf['to_component'].
#      c. Score S, O, D using same AIAG rules as Step 3.
#      d. Set interface_ref = intf['id'].
#      e. Set component_ref = intf['from_comp'] (primary component in the interface).
#      f. Link drg_indicator_ref and sc_cc_ref (interfaces often link to SC/CC items
#         via intf['sc_cc_refs']).
#      g. Compute RPN, determine action_required, generate recommended_action if needed.
#      h. Append to failure_modes list.

log.info(f"Total failure modes after interface analysis: {len(failure_modes)}")
```

---

### Step 5: Validate SC/CC coverage

```python
log.step("Step 5: Validate SC/CC coverage")

# Every SC/CC item from n03 must appear in at least one failure mode's sc_cc_ref
covered_sc_cc = {fm.get('sc_cc_ref') for fm in failure_modes if fm.get('sc_cc_ref')}
all_sc_cc_refs = {sc['sc_cc_ref'] for sc in sc_cc_items}
uncovered_sc_cc = all_sc_cc_refs - covered_sc_cc - {None}

if uncovered_sc_cc:
    log.info(f"Uncovered SC/CC items: {uncovered_sc_cc}")
    # Generate additional failure modes for uncovered SC/CC items
    for sc_ref in uncovered_sc_cc:
        # Find the SC/CC item details
        sc_item = next((s for s in sc_cc_items if s['sc_cc_ref'] == sc_ref), None)
        if sc_item:
            fm = {
                "id": make_fm_id(),
                "component_ref": sc_item['comp_id'],
                "interface_ref": None,
                "function": f"Maintain {sc_ref} within specification",
                "failure_mode": f"{sc_ref} out of specification",
                "failure_effect": "Potential safety or performance impact (SC/CC characteristic)",
                "severity": 9,  # SC/CC items are safety-critical by definition
                "failure_cause": "Process variation or design inadequacy",
                "occurrence": 5,
                "current_control_prevention": "Design spec + process control",
                "current_control_detection": "SPC monitoring or 100% test",
                "detection": 4,
                "rpn": 9 * 5 * 4,  # = 180
                "action_required": True,
                "recommended_action": f"Ensure {sc_ref} is included in control plan with SPC or 100% inspection",
                "drg_indicator_ref": find_drg_indicator(sc_ref, ""),
                "sc_cc_ref": sc_ref,
                "confidence": "S3",
            }
            failure_modes.append(fm)
            log.info(f"  Added FM for uncovered SC/CC: {sc_ref} → {fm['id']}")

log.info(f"Total failure modes after SC/CC coverage: {len(failure_modes)}")
```

---

### Step 6: Generate dfmea_corrections (feedback to n02)

```python
log.step("Step 6: Generate dfmea_corrections for n02 feedback")

# PSEUDOCODE — dfmea_corrections generation
#
# For each failure mode in failure_modes:
#   If drg_indicator_ref is None (meaning no matching DRG indicator in n02),
#   AND the failure mode has S >= 7 or RPN > 100:
#     → This is a risk not covered by n02's DRG indicators.
#     → Generate a correction entry for n02's feedback loop:
#       {
#         "target_node": "n02",
#         "action": "add_indicator",
#         "suggested_category": <best-fit category from n02 categories>,
#         "parameter": <derived from failure mode>,
#         "design_target": <derived from recommended_action or current_control>,
#         "rationale": f"DFMEA FM-{id} identified risk not covered by existing DRG indicators: {failure_mode}",
#         "source_fm_id": <FM id>
#       }
#
# dfmea_corrections = [... list of correction entries ...]
#
# If no corrections needed, dfmea_corrections = []

dfmea_corrections = []  # AI populates based on above logic

log.info(f"dfmea_corrections generated: {len(dfmea_corrections)}")
```

---

### Step 7: Compute summary statistics, gaps, and write artifact

```python
log.step("Step 7: Compute statistics, identify gaps, write artifact")

# ── Summary statistics ────────────────────────────────────────────────────────
total_failure_modes = len(failure_modes)
high_rpn_items = [fm for fm in failure_modes if fm['rpn'] > 100]
high_severity_items = [fm for fm in failure_modes if fm['severity'] >= 9]
action_required_items = [fm for fm in failure_modes if fm['action_required']]

high_rpn_count = len(high_rpn_items)
action_required_count = len(action_required_items)

log.info(f"total_failure_modes   : {total_failure_modes}")
log.info(f"high_rpn_count (>100) : {high_rpn_count}")
log.info(f"action_required_count : {action_required_count}")

# ── Gap identification ────────────────────────────────────────────────────────
gaps = []

# R-07-01: no components from n03
if len(components) == 0:
    msg = "n03 has no components — DFMEA cannot be generated"
    log.gap("R-07-01", msg, "error")
    gaps.append({"rule": "R-07-01", "msg": msg, "severity": "error", "assumption": None})

# R-07-02: high RPN items without recommended_action
high_rpn_no_action = [fm for fm in high_rpn_items if not fm.get('recommended_action')]
if high_rpn_no_action:
    ids = [fm['id'] for fm in high_rpn_no_action]
    msg = f"{len(high_rpn_no_action)} failure mode(s) with RPN>100 have no recommended_action: {ids}"
    log.gap("R-07-02", msg, "warning")
    gaps.append({"rule": "R-07-02", "msg": msg, "severity": "warning",
                 "assumption": "Engineer must review and add recommended actions"})

# R-07-03: SC/CC items not covered in DFMEA
final_covered = {fm.get('sc_cc_ref') for fm in failure_modes if fm.get('sc_cc_ref')}
final_uncovered = all_sc_cc_refs - final_covered - {None}
if final_uncovered:
    msg = f"SC/CC items not covered in any DFMEA row: {final_uncovered}"
    log.gap("R-07-03", msg, "error")
    gaps.append({"rule": "R-07-03", "msg": msg, "severity": "error",
                 "assumption": None})

# ── Confidence floor ──────────────────────────────────────────────────────────
all_confidences = [fm.get('confidence', 'S2') for fm in failure_modes]
valid_confs = [c for c in all_confidences if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S2'

# ── Assumptions ───────────────────────────────────────────────────────────────
assumptions = []
# AI populates based on actual assumptions made during scoring.
# Typical assumptions:
#   - If n03 confidence is low → occurrence scores are estimated
#   - If no test plan exists → detection scores are conservative
#   - If component type is not in lookup table → generic fallback used

# ── Build artifact ────────────────────────────────────────────────────────────
artifact = {
    "node":             "n07",
    "project":          n03.get("project"),
    "status":           "ready",
    "produced_at":      datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":             gaps,
    "assumptions":      assumptions,
    "payload": {
        "dfmea_version":        1,
        "total_failure_modes":  total_failure_modes,
        "high_rpn_count":       high_rpn_count,
        "action_required_count": action_required_count,
        "failure_modes":        failure_modes,
        "dfmea_corrections":    dfmea_corrections,
    }
}

store.write('n07', artifact)
```

---

### Step 8: Close logger

```python
log.done(artifact)
```

### Step 9: Write report

```python
# AI fills in actual values from this execution run
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| upstream | artifacts/n03-output.json | components + assembly_interfaces |
| upstream | artifacts/n02-output.json | categories with DRG indicators |

### 过程中解决的问题

- (AI fills in: e.g., "Component type 'hose' mapped to 'tube' FM table")
- (AI fills in: any scoring decisions that required judgment)

### 假设与判断

- (AI fills in each assumption made during scoring, with confidence level)

### 对 skill 的改进

- (AI fills in: e.g., "Consider adding FM table for component type X")
"""

report = NodeReport('<project_path>', 'n07')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
# → 报告写入 reports/n07-report-YYYYMMDD-HHMMSS.md
```

---

## Optimize Mode

When the engineer provides reviewed scores, additional failure modes, or test data that replaces AI estimates:

1. Read existing `artifacts/n07-output.json`
2. Initialize logger with all step titles prefixed by `[Optimize]`
3. Identify which failure modes are updated (compare new data vs existing):
   - Updated S/O/D scores → recompute RPN
   - New recommended_actions for previously flagged items
   - Engineer-confirmed confidence upgrades (S3 → S1/S2)
4. Update only affected failure_modes entries; preserve unchanged entries
5. Recompute summary statistics (`high_rpn_count`, `action_required_count`)
6. Recompute `confidence_floor` (may improve from S3 to S1/S2)
7. Remove resolved gaps and assumptions
8. Regenerate `dfmea_corrections` if risk coverage changed
9. Write artifact → close logger → write report (same as Build Steps 7-9)
10. Run Validation

### When to fall back to Build mode

The following situations exceed the scope of a local update and require a full rebuild:

- **n03 payload structure changed** (new components added/removed, interfaces changed)
- **New failure modes need to be added** (not just score updates on existing rows)
- **n02 categories were restructured** (new DRG indicators from feedback loop)
- **confidence_floor degraded** from S1/S2 to S4/S5 (data quality regression requires re-evaluation)

If in doubt, choose Build — a full rebuild is safer than a partial update.

---

## Review Mode

Inspect the existing artifact without modifying any files:

1. Read `artifacts/n07-output.json`
2. Run the Validation checks below
3. Report summary:
   - Total failure modes, high RPN count, action required count
   - SC/CC coverage status
   - dfmea_corrections count (pending feedback to n02)
   - Gaps by severity, assumptions count, confidence_floor
4. Do not write any artifact or report

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '<project_path>/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n07')
p = a.get('payload', {})

# 1. Envelope checks
assert a.get('status') in ('ready', 'done', 'waiting_human'), f"status invalid: {a.get('status')}"
assert a.get('confidence_floor'), "confidence_floor not set"

# 2. Failure modes must exist
fms = p.get('failure_modes', [])
assert len(fms) > 0, "failure_modes is empty — DFMEA has no entries"

# 3. Every failure mode must have required fields
required_fm_fields = [
    'id', 'component_ref', 'function', 'failure_mode', 'failure_effect',
    'severity', 'failure_cause', 'occurrence',
    'current_control_prevention', 'current_control_detection',
    'detection', 'rpn', 'action_required', 'confidence'
]
for fm in fms:
    for field in required_fm_fields:
        assert field in fm, f"FM {fm.get('id', '?')} missing field: {field}"

# 4. Scoring range validation
for fm in fms:
    assert 1 <= fm['severity'] <= 10, f"FM {fm['id']}: severity {fm['severity']} out of range 1-10"
    assert 1 <= fm['occurrence'] <= 10, f"FM {fm['id']}: occurrence {fm['occurrence']} out of range 1-10"
    assert 1 <= fm['detection'] <= 10, f"FM {fm['id']}: detection {fm['detection']} out of range 1-10"
    expected_rpn = fm['severity'] * fm['occurrence'] * fm['detection']
    assert fm['rpn'] == expected_rpn, \
        f"FM {fm['id']}: RPN {fm['rpn']} != S({fm['severity']}) × O({fm['occurrence']}) × D({fm['detection']}) = {expected_rpn}"

# 5. All RPN > 100 must have recommended_action
high_rpn_no_action = [fm['id'] for fm in fms if fm['rpn'] > 100 and not fm.get('recommended_action')]
assert len(high_rpn_no_action) == 0, \
    f"RPN>100 without recommended_action: {high_rpn_no_action}"

# 6. All S >= 9 must have action_required = True
high_sev_no_flag = [fm['id'] for fm in fms if fm['severity'] >= 9 and not fm['action_required']]
assert len(high_sev_no_flag) == 0, \
    f"S>=9 but action_required=False: {high_sev_no_flag}"

# 7. SC/CC coverage: every SC/CC from n03 must appear in at least one FM
n03 = store.read('n03')
if n03:
    n03_sc_cc = set()
    for comp in n03['payload'].get('components', []):
        for dim in comp.get('dimensions', []):
            if dim.get('sc_cc_ref'):
                n03_sc_cc.add(dim['sc_cc_ref'])
        for sc in comp.get('special_characteristics', []):
            ref = sc.get('parameter') or sc.get('name')
            if ref:
                n03_sc_cc.add(ref)
    fm_sc_cc = {fm.get('sc_cc_ref') for fm in fms if fm.get('sc_cc_ref')}
    uncovered = n03_sc_cc - fm_sc_cc - {None}
    assert len(uncovered) == 0, \
        f"SC/CC items from n03 not covered in DFMEA: {uncovered}"

# 8. Summary statistics consistency
assert p.get('total_failure_modes') == len(fms), \
    f"total_failure_modes ({p.get('total_failure_modes')}) != actual count ({len(fms)})"
actual_high_rpn = len([fm for fm in fms if fm['rpn'] > 100])
assert p.get('high_rpn_count') == actual_high_rpn, \
    f"high_rpn_count ({p.get('high_rpn_count')}) != actual ({actual_high_rpn})"
actual_action = len([fm for fm in fms if fm['action_required']])
assert p.get('action_required_count') == actual_action, \
    f"action_required_count ({p.get('action_required_count')}) != actual ({actual_action})"

# 9. Gaps completeness
for g in a.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

# 10. dfmea_corrections must be a list (may be empty)
assert isinstance(p.get('dfmea_corrections', []), list), "dfmea_corrections must be a list"

print(f"✓ n07 validation passed — confidence_floor: {a['confidence_floor']}")
print(f"  Total failure modes   : {len(fms)}")
print(f"  High RPN (>100)       : {actual_high_rpn}")
print(f"  Action required       : {actual_action}")
print(f"  SC/CC covered         : {len(fm_sc_cc - {None})}")
print(f"  dfmea_corrections     : {len(p.get('dfmea_corrections', []))}")
print(f"  Gaps                  : {[g['rule'] for g in a.get('gaps', [])]}")
```
