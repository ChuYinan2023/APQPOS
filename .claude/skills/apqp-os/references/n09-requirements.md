# NODE-09: DVPR（Design Verification Plan and Report）

**Purpose**: Generate a DV/PV test plan from n07 DFMEA failure modes + n02 DRG indicators + n01 test_matrix. Each test entry links explicitly to what it verifies (failure modes, DRG indicators, referenced standards).
**Input**: `artifacts/n07-output.json` (failure_modes), `artifacts/n02-output.json` (categories with DRG indicators), `artifacts/n01-output.json` (test_matrix + referenced_standards + deliverables_required D-08 DVPR template)
**Output**: `artifacts/n09-output.json`
**Type**: mixed（AI generates initial test plan; engineer reviews sample sizes, equipment, and cost estimates）

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

n07 = store.read('n07')
n02 = store.read('n02')
n01 = store.read('n01')

assert n07 and n07['status'] in ('ready', 'done'), \
    f"n07 status is '{n07['status'] if n07 else 'missing'}' — must be 'ready' or 'done' before running n09"
assert n02 and n02['status'] in ('ready', 'done'), \
    f"n02 status is '{n02['status'] if n02 else 'missing'}' — must be 'ready' or 'done' before running n09"
assert n01 and n01['status'] in ('ready', 'done'), \
    f"n01 status is '{n01['status'] if n01 else 'missing'}' — must be 'ready' or 'done' before running n09"

# Check for error-level gaps in upstream
error_gaps_total = 0
for uid, art in [('n07', n07), ('n02', n02), ('n01', n01)]:
    error_gaps = [g for g in art.get('gaps', []) if g['severity'] == 'error']
    if error_gaps:
        error_gaps_total += len(error_gaps)
        print(f"⚠ {uid} has {len(error_gaps)} error gap(s)")

if error_gaps_total:
    print(f"⚠ Upstream has {error_gaps_total} total error gap(s) — n09 results may be unreliable")

# Verify n07 has failure modes
failure_modes = n07['payload'].get('failure_modes', [])
assert len(failure_modes) > 0, "n07 has no failure_modes — cannot generate DVPR"

# Start logger
log = NodeLogger('<project_path>', 'n09')
log.step("Precondition: n07, n02, n01 ready, failure_modes present")
log.info(f"n07 confidence_floor: {n07['confidence_floor']}")
log.info(f"n02 confidence_floor: {n02['confidence_floor']}")
log.info(f"n01 confidence_floor: {n01['confidence_floor']}")
log.info(f"n07 failure_modes count: {len(failure_modes)}")
log.info(f"n07 high_rpn_count: {n07['payload'].get('high_rpn_count', 0)}")
log.info(f"n07 gaps: {[g['rule'] for g in n07.get('gaps', [])]}")
log.info(f"n02 gaps: {[g['rule'] for g in n02.get('gaps', [])]}")
log.info(f"n01 gaps: {[g['rule'] for g in n01.get('gaps', [])]}")
```

---

## Execution Steps (Build Mode)

### Step 1: Read input fields from n07, n02, and n01

```python
log.step("Step 1: Read input fields from n07, n02, and n01")

n07_payload = n07['payload']
n02_payload = n02['payload']
n01_payload = n01['payload']

# ── From n07 ──────────────────────────────────────────────────────────────────
failure_modes = n07_payload.get('failure_modes', [])

# Separate high-severity and high-RPN items for priority test coverage
high_sev_fms = [fm for fm in failure_modes if fm['severity'] >= 9]
high_rpn_fms = [fm for fm in failure_modes if fm['rpn'] > 100]
action_required_fms = [fm for fm in failure_modes if fm['action_required']]

# ── From n02: collect ALL indicators across ALL categories ────────────────────
all_indicators = []
categories = n02_payload.get('categories', [])
for cat in categories:
    for ind in cat.get('indicators', []):
        ind['_category_id'] = cat.get('id')
        ind['_category_name'] = cat.get('name', '')
        all_indicators.append(ind)

# ── From n01: test_matrix, referenced_standards, deliverables_required ────────
test_matrix = n01_payload.get('test_matrix', [])
referenced_standards = n01_payload.get('referenced_standards', [])
deliverables_required = n01_payload.get('deliverables_required', [])

# Build a lookup set of available standard IDs for gap rule R-09-02
available_standard_ids = set()
for std in referenced_standards:
    std_id = std.get('id') or std.get('standard_id') or std.get('name', '')
    available_standard_ids.add(std_id)

# Check if D-08 (DVPR template) is in deliverables_required
dvpr_deliverable = next(
    (d for d in deliverables_required if 'D-08' in str(d.get('id', '')) or 'DVPR' in str(d.get('name', '')).upper()),
    None
)

log.info(f"failure_modes         : {len(failure_modes)}")
log.info(f"  high severity (S>=9): {len(high_sev_fms)}")
log.info(f"  high RPN (>100)     : {len(high_rpn_fms)}")
log.info(f"  action_required     : {len(action_required_fms)}")
log.info(f"n02 indicators        : {len(all_indicators)}")
log.info(f"n01 test_matrix       : {len(test_matrix)}")
log.info(f"n01 referenced_standards: {len(referenced_standards)}")
log.info(f"n01 deliverables_required: {len(deliverables_required)}")
log.info(f"D-08 DVPR deliverable : {'found' if dvpr_deliverable else 'not found'}")
```

---

### Step 2: Build test requirement map from inputs

> **DESIGN RULE** — Tests originate from three sources. The AI merges them
> into a unified test plan, avoiding duplicate tests while ensuring complete
> traceability to failure modes and DRG indicators.

```python
log.step("Step 2: Build test requirement map from inputs")

# ── Source A: n01 test_matrix ─────────────────────────────────────────────────
# test_matrix entries from the customer specification already define required
# tests. Each entry may have: test_name, standard, acceptance_criteria, phase.
# These are "must have" tests — the DVPR must include all of them.

# ── Source B: n07 failure_modes ───────────────────────────────────────────────
# Each failure mode has current_control_detection which implies a test method.
# For every FM with S >= 9 or action_required == True, a corresponding test
# MUST exist in the DVPR.

# ── Source C: n02 DRG indicators ──────────────────────────────────────────────
# DRG indicators define performance requirements (e.g., burst pressure,
# leak rate, vibration endurance). Each indicator with a measurable
# design_target should map to at least one test.

# ── Helper: ID generator ─────────────────────────────────────────────────────
_test_counter = 0
def make_test_id() -> str:
    global _test_counter
    _test_counter += 1
    return f"T-{_test_counter:03d}"

# ── Helper: find DRG indicator matching a test or failure mode ────────────────
def find_matching_indicators(test_name: str, fm_text: str = "") -> list[str]:
    """
    Search all_indicators for DRG indicators relevant to a test.
    Returns list of indicator IDs.
    """
    combined_text = (test_name + " " + fm_text).lower()
    keywords = [w for w in combined_text.split() if len(w) > 3]
    matches = []
    for ind in all_indicators:
        param = (ind.get('parameter', '') or '').lower()
        target = (ind.get('design_target', '') or '').lower()
        score = sum(1 for kw in keywords if kw in param or kw in target)
        if score >= 1:
            matches.append(ind.get('id'))
    return matches

# ── Helper: find failure modes covered by a test ─────────────────────────────
def find_covered_fms(test_name: str, test_standard: str = "") -> list[str]:
    """
    Search failure_modes for entries whose current_control_detection
    or failure_mode text is relevant to this test.
    Returns list of FM IDs.
    """
    combined_text = (test_name + " " + test_standard).lower()
    keywords = [w for w in combined_text.split() if len(w) > 3]
    matches = []
    for fm in failure_modes:
        detection = (fm.get('current_control_detection', '') or '').lower()
        fm_text = (fm.get('failure_mode', '') or '').lower()
        score = sum(1 for kw in keywords if kw in detection or kw in fm_text)
        if score >= 1:
            matches.append(fm['id'])
    return matches

log.info("Test requirement map helpers defined")
```

---

### Step 3: Generate test entries

> **PSEUDOCODE** — AI executes this logic inline, adapting test parameters
> to the specific project context. Do not run this block directly.

```python
log.step("Step 3: Generate test entries")

# PSEUDOCODE — Test entry generation
#
# tests = []
#
# ── Phase 1: Seed from n01 test_matrix ────────────────────────────────────────
# For each entry in test_matrix:
#   1. Create a test entry with:
#      test_id          = make_test_id()
#      test_name        = entry['test_name'] (from customer spec)
#      spec_reference   = entry['standard'] or entry['spec_reference']
#      acceptance_criteria = entry['acceptance_criteria'] or entry['requirement']
#      phase            = entry.get('phase', 'DV')  # DV, PV, or CC
#   2. Link to failure modes:
#      dfmea_refs = find_covered_fms(test_name, spec_reference)
#   3. Link to DRG indicators:
#      drg_refs = find_matching_indicators(test_name)
#   4. Assign defaults for fields the AI will estimate:
#      sample_size       = derive from phase and standard
#                          (DV: typically 3-5 parts; PV: per standard; CC: per SPC rule)
#      reliability_target = derive from standard or customer requirement
#                          (e.g., "B10 life 1,000,000 cycles" or "zero failures at 95% CL")
#      responsible       = "supplier" (default, unless customer spec states "OEM")
#      equipment_needed  = derive from test type (e.g., "burst test bench", "helium leak detector")
#      estimated_duration_days = AI estimate based on test complexity
#      estimated_cost_eur     = AI estimate based on equipment and sample count
#      confidence        = "S2" (from customer spec, fairly reliable)
#   5. Append to tests.
#
# ── Phase 2: Generate tests from n07 failure modes ───────────────────────────
# For each failure mode in failure_modes where action_required == True
#   OR severity >= 9:
#   1. Check if this FM is already covered by a test from Phase 1
#      (i.e., fm['id'] appears in any existing test's dfmea_refs).
#   2. If NOT covered:
#      a. Derive test_name from fm['current_control_detection'].
#         - Clean up detection text into a proper test name
#           (e.g., "Leak test (helium or pressure decay)" → "Helium Leak Test")
#      b. Derive spec_reference from referenced_standards:
#         - Match by keyword (e.g., "leak" → leak test standard, "burst" → burst standard)
#         - If no match, set to "TBD — to be defined by engineering"
#      c. Derive acceptance_criteria from fm['failure_mode'] + fm['failure_effect']:
#         - "No [failure_mode] allowed" or specific limit from DRG indicator
#      d. phase = "DV" for design verification; "PV" if production validation needed
#      e. dfmea_refs = [fm['id']]
#      f. drg_refs = find_matching_indicators(test_name, fm['failure_mode'])
#      g. Set sample_size, reliability_target, responsible, equipment_needed,
#         estimated_duration_days, estimated_cost_eur, confidence.
#         - confidence = "S3" (AI-derived from DFMEA, not from spec)
#      h. Append to tests.
#   3. If already covered:
#      - Ensure the existing test's dfmea_refs includes this FM ID
#        (may already be there from find_covered_fms, but verify).
#
# ── Phase 3: Ensure DRG indicator coverage ───────────────────────────────────
# For each indicator in all_indicators:
#   1. Check if this indicator's ID appears in any test's drg_refs.
#   2. If NOT covered AND indicator has a measurable design_target:
#      a. Create a test entry:
#         test_name = f"Verify {indicator['parameter']}"
#         spec_reference = derive from indicator or referenced_standards
#         acceptance_criteria = indicator['design_target']
#         phase = "DV"
#      b. dfmea_refs = find_covered_fms(test_name)
#      c. drg_refs = [indicator['id']]
#      d. confidence = "S3"
#      e. Append to tests.
#
# ── Phase 4: Consolidate duplicates ──────────────────────────────────────────
# Merge tests that have the same test method and spec_reference:
#   - Combine dfmea_refs and drg_refs (union)
#   - Keep the more specific acceptance_criteria
#   - Take the larger sample_size
#   - Keep a single test_id (renumber sequentially at the end)

tests = []  # AI populates based on above logic

log.info(f"Test entries generated: {len(tests)}")
```

---

### Step 4: Validate DFMEA coverage (gap rule R-09-01)

```python
log.step("Step 4: Validate DFMEA coverage — gap rule R-09-01")

# R-09-01: Every DFMEA failure mode with S >= 9 MUST be covered by at least
#           one test in the DVPR. Missing coverage is an ERROR.

all_test_dfmea_refs = set()
for t in tests:
    for ref in t.get('dfmea_refs', []):
        all_test_dfmea_refs.add(ref)

uncovered_high_sev = []
for fm in failure_modes:
    if fm['severity'] >= 9 and fm['id'] not in all_test_dfmea_refs:
        uncovered_high_sev.append(fm['id'])

if uncovered_high_sev:
    log.info(f"R-09-01 violation: {len(uncovered_high_sev)} high-severity FM(s) not covered by any test")
    for fm_id in uncovered_high_sev:
        log.info(f"  {fm_id}: S >= 9, no test assigned")
    # Generate additional tests to close the gap
    for fm_id in uncovered_high_sev:
        fm = next(f for f in failure_modes if f['id'] == fm_id)
        # Create a minimal test entry to cover this FM
        t = {
            "test_id": make_test_id(),
            "test_name": f"Verify against {fm['failure_mode']}",
            "spec_reference": "TBD — to be defined by engineering",
            "acceptance_criteria": f"No occurrence of: {fm['failure_mode']}",
            "phase": "DV",
            "sample_size": "TBD",
            "reliability_target": "TBD",
            "dfmea_refs": [fm_id],
            "drg_refs": find_matching_indicators(fm.get('failure_mode', ''), ''),
            "responsible": "supplier",
            "equipment_needed": "TBD",
            "estimated_duration_days": None,
            "estimated_cost_eur": None,
            "confidence": "S4",
        }
        tests.append(t)
        log.info(f"  Added gap-closing test {t['test_id']} for {fm_id}")

log.info(f"Tests after R-09-01 coverage check: {len(tests)}")
```

---

### Step 5: Validate standard references (gap rule R-09-02)

```python
log.step("Step 5: Validate standard references — gap rule R-09-02")

# R-09-02: If a test references a standard that is NOT in n01 referenced_standards,
#           flag a WARNING. The standard may be valid but was not listed in the
#           customer specification — engineering must confirm availability.

tests_with_unknown_std = []
for t in tests:
    spec_ref = t.get('spec_reference', '') or ''
    if spec_ref and spec_ref != 'TBD — to be defined by engineering':
        # Check if the spec_reference matches any known standard
        matched = False
        for std_id in available_standard_ids:
            if std_id and (std_id.lower() in spec_ref.lower() or spec_ref.lower() in std_id.lower()):
                matched = True
                break
        if not matched:
            tests_with_unknown_std.append((t['test_id'], spec_ref))

if tests_with_unknown_std:
    log.info(f"R-09-02: {len(tests_with_unknown_std)} test(s) reference standard(s) not in n01")
    for tid, std in tests_with_unknown_std:
        log.info(f"  {tid}: {std}")

log.info(f"R-09-02 check complete")
```

---

### Step 6: Compute summary statistics, gaps, and write artifact

```python
log.step("Step 6: Compute statistics, identify gaps, write artifact")

# ── Summary statistics ────────────────────────────────────────────────────────
total_tests = len(tests)
dv_tests = [t for t in tests if t.get('phase') == 'DV']
pv_tests = [t for t in tests if t.get('phase') == 'PV']
cc_tests = [t for t in tests if t.get('phase') == 'CC']

# Count how many unique failure modes are covered
all_covered_fms = set()
for t in tests:
    for ref in t.get('dfmea_refs', []):
        all_covered_fms.add(ref)
fm_coverage_ratio = len(all_covered_fms) / len(failure_modes) if failure_modes else 0

# Count how many unique DRG indicators are covered
all_covered_drg = set()
for t in tests:
    for ref in t.get('drg_refs', []):
        all_covered_drg.add(ref)
drg_coverage_ratio = len(all_covered_drg) / len(all_indicators) if all_indicators else 0

log.info(f"total_tests          : {total_tests}")
log.info(f"  DV tests           : {len(dv_tests)}")
log.info(f"  PV tests           : {len(pv_tests)}")
log.info(f"  CC tests           : {len(cc_tests)}")
log.info(f"FM coverage          : {len(all_covered_fms)}/{len(failure_modes)} ({fm_coverage_ratio:.0%})")
log.info(f"DRG indicator coverage: {len(all_covered_drg)}/{len(all_indicators)} ({drg_coverage_ratio:.0%})")

# ── Gap identification ────────────────────────────────────────────────────────
gaps = []

# R-09-01: DFMEA failure mode with S >= 9 not covered by any test (error)
# We already attempted to close these in Step 4, but record any that remain
# with TBD test definitions as gaps.
final_uncovered_high_sev = []
for fm in failure_modes:
    if fm['severity'] >= 9 and fm['id'] not in all_covered_fms:
        final_uncovered_high_sev.append(fm['id'])

if final_uncovered_high_sev:
    msg = (f"{len(final_uncovered_high_sev)} DFMEA failure mode(s) with S>=9 "
           f"not covered by any test: {final_uncovered_high_sev}")
    log.gap("R-09-01", msg, "error")
    gaps.append({"rule": "R-09-01", "msg": msg, "severity": "error", "assumption": None})

# Also flag any gap-closing tests (TBD entries) as warnings
tbd_tests = [t for t in tests if t.get('spec_reference') == 'TBD — to be defined by engineering']
if tbd_tests:
    ids = [t['test_id'] for t in tbd_tests]
    msg = f"{len(tbd_tests)} test(s) have TBD spec_reference — engineering must define: {ids}"
    log.gap("R-09-01", msg, "warning")
    gaps.append({"rule": "R-09-01", "msg": msg, "severity": "warning",
                 "assumption": "Gap-closing tests added with TBD details; engineer must complete"})

# R-09-02: test references unavailable standard (warning)
if tests_with_unknown_std:
    ids_stds = [f"{tid} → {std}" for tid, std in tests_with_unknown_std]
    msg = f"{len(tests_with_unknown_std)} test(s) reference standard(s) not in n01 referenced_standards: {ids_stds}"
    log.gap("R-09-02", msg, "warning")
    gaps.append({"rule": "R-09-02", "msg": msg, "severity": "warning",
                 "assumption": "Standards may be valid but not listed in customer spec — engineering to confirm"})

# ── Confidence floor ──────────────────────────────────────────────────────────
all_confidences = [t.get('confidence', 'S2') for t in tests]
valid_confs = [c for c in all_confidences if c and c.startswith('S') and c[1:].isdigit()]
confidence_floor = max(valid_confs, key=lambda s: int(s[1:])) if valid_confs else 'S3'

# ── Assumptions ───────────────────────────────────────────────────────────────
assumptions = []
# AI populates based on actual assumptions made during test plan generation.
# Typical assumptions:
#   - Sample sizes estimated from standard practice when not specified by customer
#   - Equipment and cost estimates based on industry benchmarks
#   - Reliability targets derived from referenced standards when not explicit
#   - Phase assignment (DV vs PV) based on test type when not specified

# ── Build artifact ────────────────────────────────────────────────────────────
artifact = {
    "node":             "n09",
    "project":          n07.get("project"),
    "status":           "ready",
    "produced_at":      datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps":             gaps,
    "assumptions":      assumptions,
    "payload": {
        "dvpr_version":         1,
        "total_tests":          total_tests,
        "dv_test_count":        len(dv_tests),
        "pv_test_count":        len(pv_tests),
        "cc_test_count":        len(cc_tests),
        "fm_coverage_ratio":    round(fm_coverage_ratio, 2),
        "drg_coverage_ratio":   round(drg_coverage_ratio, 2),
        "tests":                tests,
    }
}

store.write('n09', artifact)
```

> **Test entry schema** — each element in `tests` has the following fields:
>
> | Field | Type | Description |
> |-------|------|-------------|
> | `test_id` | string | Unique ID, e.g. `"T-001"` |
> | `test_name` | string | Human-readable test name |
> | `spec_reference` | string | Standard or specification (e.g. `"SAE J2044"`) |
> | `acceptance_criteria` | string | Pass/fail criteria |
> | `phase` | string | `"DV"`, `"PV"`, or `"CC"` |
> | `sample_size` | string/int | Number of samples or `"per standard"` |
> | `reliability_target` | string | e.g. `"zero failures at 95% CL"` |
> | `dfmea_refs` | list[str] | FM IDs this test covers (e.g. `["FM-001", "FM-005"]`) |
> | `drg_refs` | list[str] | DRG indicator IDs (e.g. `["IND-03"]`) |
> | `responsible` | string | `"supplier"` or `"OEM"` |
> | `equipment_needed` | string | Test equipment description |
> | `estimated_duration_days` | int/null | Estimated calendar days |
> | `estimated_cost_eur` | number/null | Estimated cost in EUR |
> | `confidence` | string | `"S1"` to `"S5"` |

---

### Step 7: Close logger

```python
log.done(artifact)
```

### Step 8: Write report

```python
# AI fills in actual values from this execution run
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| upstream | artifacts/n07-output.json | failure_modes (DFMEA) |
| upstream | artifacts/n02-output.json | categories with DRG indicators |
| upstream | artifacts/n01-output.json | test_matrix + referenced_standards + deliverables_required |

### 过程中解决的问题

- (AI fills in: e.g., "Merged 3 duplicate tests from test_matrix and DFMEA detection controls")
- (AI fills in: e.g., "Mapped FM-012 detection 'leak test' to SAE J1737 from referenced_standards")

### 假设与判断

- (AI fills in each assumption made during test plan generation, with confidence level)

### 对 skill 的改进

- (AI fills in: e.g., "Consider adding test duration/cost lookup tables by test type")
"""

report = NodeReport('<project_path>', 'n09')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
# → 报告写入 reports/n09-report-YYYYMMDD-HHMMSS.md
```

---

## Optimize Mode

When the engineer provides reviewed test parameters, additional tests, or lab data that replaces AI estimates:

1. Read existing `artifacts/n09-output.json`
2. Initialize logger with all step titles prefixed by `[Optimize]`
3. Identify which tests are updated (compare new data vs existing):
   - Updated sample_size, equipment_needed, estimated_cost_eur → recalculate totals
   - Updated acceptance_criteria with actual measured values
   - Engineer-confirmed confidence upgrades (S3 → S1/S2)
   - New dfmea_refs or drg_refs added to existing tests
4. Update only affected test entries; preserve unchanged entries
5. Recompute summary statistics (`fm_coverage_ratio`, `drg_coverage_ratio`, phase counts)
6. Recompute `confidence_floor` (may improve from S3/S4 to S1/S2)
7. Remove resolved gaps and assumptions
8. Write artifact → close logger → write report (same as Build Steps 6-8)
9. Run Validation

### When to fall back to Build mode

The following situations exceed the scope of a local update and require a full rebuild:

- **n07 payload structure changed** (new failure modes added/removed, scores significantly revised)
- **n01 test_matrix updated** (customer added new required tests)
- **n02 categories were restructured** (new DRG indicators from feedback loop)
- **New tests need to be added** that are not updates to existing entries
- **confidence_floor degraded** from S1/S2 to S4/S5 (data quality regression requires re-evaluation)

If in doubt, choose Build — a full rebuild is safer than a partial update.

---

## Review Mode

Inspect the existing artifact without modifying any files:

1. Read `artifacts/n09-output.json`
2. Run the Validation checks below
3. Report summary:
   - Total tests, breakdown by phase (DV/PV/CC)
   - FM coverage ratio (especially S >= 9 coverage)
   - DRG indicator coverage ratio
   - Tests with TBD spec_reference or acceptance_criteria
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
a = store.read('n09')
p = a.get('payload', {})

# 1. Envelope checks
assert a.get('status') in ('ready', 'done', 'waiting_human'), f"status invalid: {a.get('status')}"
assert a.get('confidence_floor'), "confidence_floor not set"

# 2. Tests must exist
tests = p.get('tests', [])
assert len(tests) > 0, "tests is empty — DVPR has no entries"

# 3. Every test must have required fields
required_test_fields = [
    'test_id', 'test_name', 'spec_reference', 'acceptance_criteria',
    'phase', 'sample_size', 'reliability_target',
    'dfmea_refs', 'drg_refs', 'responsible',
    'equipment_needed', 'estimated_duration_days', 'estimated_cost_eur',
    'confidence'
]
for t in tests:
    for field in required_test_fields:
        assert field in t, f"Test {t.get('test_id', '?')} missing field: {field}"

# 4. Phase must be valid
valid_phases = {'DV', 'PV', 'CC'}
for t in tests:
    assert t['phase'] in valid_phases, \
        f"Test {t['test_id']}: phase '{t['phase']}' not in {valid_phases}"

# 5. dfmea_refs and drg_refs must be lists
for t in tests:
    assert isinstance(t['dfmea_refs'], list), \
        f"Test {t['test_id']}: dfmea_refs must be a list"
    assert isinstance(t['drg_refs'], list), \
        f"Test {t['test_id']}: drg_refs must be a list"

# 6. R-09-01: Every DFMEA FM with S >= 9 must be covered by at least one test
n07 = store.read('n07')
if n07:
    fms = n07['payload'].get('failure_modes', [])
    all_test_fm_refs = set()
    for t in tests:
        for ref in t.get('dfmea_refs', []):
            all_test_fm_refs.add(ref)
    uncovered_high_sev = [
        fm['id'] for fm in fms
        if fm['severity'] >= 9 and fm['id'] not in all_test_fm_refs
    ]
    assert len(uncovered_high_sev) == 0, \
        f"R-09-01 violation: DFMEA FM(s) with S>=9 not covered by any test: {uncovered_high_sev}"

# 7. R-09-02: Check for tests referencing unavailable standards
n01 = store.read('n01')
if n01:
    ref_stds = n01['payload'].get('referenced_standards', [])
    available_std_ids = set()
    for std in ref_stds:
        std_id = std.get('id') or std.get('standard_id') or std.get('name', '')
        available_std_ids.add(std_id.lower())
    unknown_std_tests = []
    for t in tests:
        spec_ref = (t.get('spec_reference', '') or '').strip()
        if spec_ref and 'TBD' not in spec_ref:
            matched = any(
                sid and (sid in spec_ref.lower() or spec_ref.lower() in sid)
                for sid in available_std_ids
            )
            if not matched:
                unknown_std_tests.append(t['test_id'])
    # R-09-02 is a warning, not an assertion failure — just report
    if unknown_std_tests:
        print(f"⚠ R-09-02: {len(unknown_std_tests)} test(s) reference standard(s) not in n01: {unknown_std_tests}")

# 8. Summary statistics consistency
assert p.get('total_tests') == len(tests), \
    f"total_tests ({p.get('total_tests')}) != actual count ({len(tests)})"
actual_dv = len([t for t in tests if t['phase'] == 'DV'])
assert p.get('dv_test_count') == actual_dv, \
    f"dv_test_count ({p.get('dv_test_count')}) != actual ({actual_dv})"
actual_pv = len([t for t in tests if t['phase'] == 'PV'])
assert p.get('pv_test_count') == actual_pv, \
    f"pv_test_count ({p.get('pv_test_count')}) != actual ({actual_pv})"
actual_cc = len([t for t in tests if t['phase'] == 'CC'])
assert p.get('cc_test_count') == actual_cc, \
    f"cc_test_count ({p.get('cc_test_count')}) != actual ({actual_cc})"

# 9. responsible must be valid
valid_responsible = {'supplier', 'OEM'}
for t in tests:
    assert t['responsible'] in valid_responsible, \
        f"Test {t['test_id']}: responsible '{t['responsible']}' not in {valid_responsible}"

# 10. Gaps completeness
for g in a.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap format incomplete: {g}"

# ── Print summary ─────────────────────────────────────────────────────────────
print(f"✓ n09 validation passed — confidence_floor: {a['confidence_floor']}")
print(f"  Total tests           : {len(tests)}")
print(f"  DV / PV / CC          : {actual_dv} / {actual_pv} / {actual_cc}")
print(f"  FM coverage ratio     : {p.get('fm_coverage_ratio', 'N/A')}")
print(f"  DRG coverage ratio    : {p.get('drg_coverage_ratio', 'N/A')}")
print(f"  Gaps                  : {[g['rule'] for g in a.get('gaps', [])]}")
```
