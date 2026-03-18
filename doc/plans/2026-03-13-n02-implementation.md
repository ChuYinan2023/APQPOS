# n02 DRG 设计要求指南 — 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 n02 节点执行指南及配套脚本支持，使 AI 能从任意项目的 n01 输出中自动生成分类量化的 DRG 指标表。

**Architecture:** n02-requirements.md 作为 AI 执行剧本（类比 n01-requirements.md），复用现有 logger/store/reporter/extraction_matrix 脚本库。reporter.py 新增 `_n02_sections()` 方法以生成可读报告。

**Tech Stack:** Python 3.11+, 现有 apqp-os scripts (logger, store, reporter, extraction_matrix)

**设计文档:** `doc/plans/2026-03-13-n02-design.md`

---

## Task 1: 修正 reporter.py 的 NODE_NAMES 和 NEXT_NODES

reporter.py 当前的节点名称和下游关系与 network.json 不符，先修正再继续。

**Files:**
- Modify: `.claude/skills/apqp-os/scripts/reporter.py:16-41`

**Step 1: 对照 network.json 写失败测试**

创建 `/tmp/test_reporter_nodes.py`:

```python
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from reporter import NODE_NAMES, NEXT_NODES

# n02 正确名称
assert NODE_NAMES['n02'] == 'DRG 设计要求指南', f"got: {NODE_NAMES['n02']}"

# n02 下游：n03, n07, n09（来自 network.json）
assert set(NEXT_NODES['n02']) == {'n03', 'n07', 'n09'}, f"got: {NEXT_NODES['n02']}"

# n01 下游：n02（主干）+ n09, n14, n18（次要边，从 network.json）
assert 'n02' in NEXT_NODES['n01'], f"n01→n02 missing"

print("✓ NODE_NAMES and NEXT_NODES correct")
```

**Step 2: 运行验证失败**

```bash
python3 /tmp/test_reporter_nodes.py
```
预期: `AssertionError: got: Drawing Parser`

**Step 3: 修正 NODE_NAMES 和 NEXT_NODES**

在 `reporter.py` 替换：

```python
NODE_NAMES = {
    "n01": "Requirements Parser",
    "n02": "DRG 设计要求指南",
    "n03": "3D 数模解析",
    "n04": "BOM",
    "n05": "材料选型",
    "n06": "用量计算",
    "n07": "DFMEA",
    "n08": "工艺路线",
    "n09": "DVP&R 验证计划",
    "n10": "PFD + 控制计划",
    "n11": "物料成本",
    "n12": "转化成本",
    "n13": "生产能力物理载体",
    "n14": "项目计划",
    "n15": "ED&D 工程开发费",
    "n16": "RC 单件成本",
    "n17": "NRC 总开发投入",
    "n18": "报价",
}

NEXT_NODES = {
    "n01": ["n02", "n09", "n14", "n18"],
    "n02": ["n03", "n07", "n09"],
    "n03": ["n04", "n05", "n06", "n07", "n08"],
    "n04": ["n05", "n06", "n10"],
    "n05": ["n11"],
    "n06": ["n11"],
    "n07": ["n09", "n08", "n02"],   # n02 是反馈边
    "n08": ["n10", "n11", "n12", "n13"],
    "n09": ["n15"],
    "n10": ["n13"],
    "n11": ["n16"],
    "n12": ["n16"],
    "n13": ["n17"],
    "n14": ["n15"],
    "n15": ["n17"],
    "n16": ["n18"],
    "n17": ["n18"],
}
```

**Step 4: 运行验证通过**

```bash
python3 /tmp/test_reporter_nodes.py
```
预期: `✓ NODE_NAMES and NEXT_NODES correct`

**Step 5: Commit**

```bash
git add .claude/skills/apqp-os/scripts/reporter.py
git commit -m "fix: correct reporter NODE_NAMES and NEXT_NODES to match network.json"
```

---

## Task 2: 为 reporter.py 新增 _n02_sections()

**Files:**
- Modify: `.claude/skills/apqp-os/scripts/reporter.py`

**Step 1: 写失败测试**

创建 `/tmp/test_n02_report.py`:

```python
import sys, json
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from reporter import NodeReport

artifact = {
    "node": "n02", "project": "TEST", "status": "ready",
    "confidence_floor": "S1",
    "gaps": [{"rule": "R-02-02", "msg": "3 条指标待审阅", "severity": "warning", "assumption": None}],
    "assumptions": [],
    "payload": {
        "drg_version": 1,
        "review_required_count": 3,
        "conflict_count": 1,
        "review_items": [
            {"id": "DRG-007", "reason": "requirement_descriptive", "detail": "无数值"},
            {"id": "DRG-012", "reason": "conflict",               "detail": "两处来源不一致"},
            {"id": "DRG-019", "reason": "low_confidence",         "detail": "S5 AI 推断"},
        ],
        "categories": [
            {
                "id": "CAT-01", "name": "功能性能",
                "indicators": [
                    {
                        "id": "DRG-001", "parameter": "密封压力",
                        "requirement_raw": "No leak at 150 PSI",
                        "design_target": "密封面 Ra ≤ 0.8µm",
                        "quantified": True, "value": 150, "unit": "PSI",
                        "test_ref": "§7.2", "acceptance_criteria": "P99C90",
                        "source_n01": "performance_requirements[PR-013]",
                        "confidence": "S1", "needs_review": False,
                        "review_reason": None, "conflict": None, "dfmea_correction": None
                    }
                ]
            }
        ]
    }
}

import tempfile, os
with tempfile.TemporaryDirectory() as tmp:
    r = NodeReport(tmp, 'n02')
    path = r.write(artifact)
    text = path.read_text()

    assert "DRG 设计要求指南" in text, "节点名称缺失"
    assert "功能性能" in text,         "分类名称缺失"
    assert "DRG-001" in text,         "指标 ID 缺失"
    assert "待审阅" in text,           "审阅汇总缺失"
    assert "conflict" in text or "冲突" in text, "冲突标注缺失"

print("✓ n02 report sections work")
```

**Step 2: 运行验证失败**

```bash
python3 /tmp/test_n02_report.py
```
预期: 报告生成但内容缺失（走 `_generic_payload_section`，无分类/指标）

**Step 3: 在 `_build()` 中分发 n02**

在 reporter.py `_build()` 的 node-specific sections 处添加分支：

```python
if self.node_id == "n01":
    L += self._n01_sections(p, artifact)
elif self.node_id == "n02":
    L += self._n02_sections(p, artifact)
else:
    L += self._generic_payload_section(p)
```

**Step 4: 实现 `_n02_sections()`**

在 reporter.py 末尾追加（`_n01_sections` 之后）：

```python
def _n02_sections(self, p: dict, artifact: dict) -> list[str]:
    L = []

    # ── 汇总 ────────────────────────────────────────────────────────
    version = p.get("drg_version", 1)
    review_n = p.get("review_required_count", 0)
    conflict_n = p.get("conflict_count", 0)
    cats = p.get("categories", [])
    total_indicators = sum(len(c.get("indicators", [])) for c in cats)

    L += [
        "## DRG 指标总览",
        "",
        f"| 版本 | 总指标数 | 待审阅 | 冲突 | 分类数 |",
        f"|------|---------|------|------|------|",
        f"| v{version} | {total_indicators} | {review_n} | {conflict_n} | {len(cats)} |",
        "",
    ]

    # ── 待审阅汇总（优先展示，方便工程师一次处理）──────────────────────
    review_items = p.get("review_items", [])
    if review_items:
        reason_label = {
            "requirement_descriptive": "描述性要求（无数值）",
            "conflict":               "来源冲突",
            "low_confidence":         "低置信度（AI 推断）",
        }
        L += ["## ⚠️ 待审阅条目", ""]
        L.append("| 指标 ID | 原因 | 说明 |")
        L.append("|---------|------|------|")
        for item in review_items:
            label = reason_label.get(item.get("reason", ""), item.get("reason", ""))
            L.append(f"| `{item['id']}` | {label} | {item.get('detail', '')} |")
        L.append("")

    # ── 分类指标详情 ─────────────────────────────────────────────────
    L += ["## DRG 指标明细", ""]
    for cat in cats:
        L += [f"### {cat['id']} — {cat['name']}", ""]
        indicators = cat.get("indicators", [])
        if not indicators:
            continue
        L.append("| ID | 参数 | 设计目标 | 量化 | 置信度 | 审阅 |")
        L.append("|----|------|---------|------|------|------|")
        for ind in indicators:
            quantified = "✓" if ind.get("quantified") else "—"
            review = "⚠️" if ind.get("needs_review") else "✓"
            conf = ind.get("confidence", "")
            target = ind.get("design_target", "")[:50]  # 截断避免表格过宽
            L.append(
                f"| `{ind['id']}` | {ind.get('parameter','')} "
                f"| {target} | {quantified} | {conf} | {review} |"
            )
        L.append("")

    # ── DFMEA 修正（如有）────────────────────────────────────────────
    dfmea_revised = []
    for cat in cats:
        for ind in cat.get("indicators", []):
            if ind.get("dfmea_correction"):
                dfmea_revised.append(ind)
    if dfmea_revised:
        L += ["## DFMEA 反馈修正", ""]
        for ind in dfmea_revised:
            dc = ind["dfmea_correction"]
            L += [
                f"**`{ind['id']}`** {ind.get('parameter','')}",
                f"- Gap 来源: `{dc.get('gap_ref','')}`",
                f"- 原目标: {dc.get('original_target','')}",
                f"- 修订目标: {dc.get('revised_target','')}",
                "",
            ]

    return L
```

**Step 5: 同时更新 print_summary() 支持 n02**

在 `print_summary()` 的 counts 循环后添加：

```python
# n02 专属摘要
if self.node_id == "n02":
    cats = p.get("categories", [])
    total = sum(len(c.get("indicators", [])) for c in cats)
    review_n = p.get("review_required_count", 0)
    if total:
        print(f"    DRG 指标: {total} 条 ({len(cats)} 类) | 待审阅: {review_n}")
```

**Step 6: 运行测试通过**

```bash
python3 /tmp/test_n02_report.py
```
预期: `✓ n02 report sections work`

**Step 7: Commit**

```bash
git add .claude/skills/apqp-os/scripts/reporter.py
git commit -m "feat: add n02 DRG report sections to reporter.py"
```

---

## Task 3: 编写 n02-requirements.md

**Files:**
- Create: `.claude/skills/apqp-os/references/n02-requirements.md`

**Step 1: 创建文件骨架，写 Precondition**

```markdown
# NODE-02: DRG 设计要求指南（Design Requirements Guide）

**Purpose**: 将 n01 解析的规范条款翻译成分类量化的工程设计目标，
标注不确定/冲突条目供工程师审阅。
**Input**: `artifacts/n01-output.json`
**Output**: `artifacts/n02-output.json`
**Type**: auto（AI 全自动；待审阅条目需工程师确认后方可进入下游）

---

## Precondition Check

​```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore(str(p))
n01 = store.read('n01')
assert n01['status'] == 'ready', "n01 not ready"
assert n01['payload'].get('performance_requirements'), "n01 performance_requirements empty"
log = NodeLogger(str(p), 'n02')
log.step("Precondition: n01 ready")
​```
```

**Step 2: 补充 Step 1 — 读取 n01 字段**

```markdown
### Step 1: 读取 n01 Payload

​```python
log.step("Step 1: Load n01 fields")
payload = n01['payload']

perf_reqs      = payload.get('performance_requirements', [])
test_matrix    = payload.get('test_matrix', [])
sc_cc          = payload.get('special_characteristics', [])
geometry       = payload.get('geometry', {})
material       = payload.get('material_compliance', {})
quality_targets= payload.get('quality_targets', {})
standards      = payload.get('referenced_standards', [])

log.info(f"performance_requirements: {len(perf_reqs)}")
log.info(f"test_matrix: {len(test_matrix)}")
log.info(f"special_characteristics: {len(sc_cc)}")
​```
```

**Step 3: 补充 Step 2 — 分类与量化**

```markdown
### Step 2: 分类 + 量化 + 审阅标注

对每条需求执行三步处理：

1. **归类**：根据参数语义归入 8 类（CAT-01 到 CAT-08）
2. **量化**：若原文含数值 → 提取 value/unit，`quantified=true`；
   仅描述性 → `quantified=false`, `needs_review=true`, `review_reason="requirement_descriptive"`
3. **冲突检测**：同一参数在多处来源出现时比对数值，不一致则
   `needs_review=true`, `review_reason="conflict"`, `conflict={"sources":[...], "values":[...]}`

**归类规则（通用，不针对特定产品类型）：**

| 关键词/语义 | 归入分类 |
|------------|---------|
| leak / seal / pressure / flow | CAT-01 功能性能（主功能） |
| burst / pull-off / vibration / fatigue / strength | CAT-02 结构完整性 |
| temperature / corrosion / chemical / UV / humidity | CAT-03 环境耐受 |
| dimension / tolerance / OD / ID / Cpk / GD&T | CAT-04 尺寸符合性 |
| material / ELV / REACH / IMDS / substance | CAT-05 材料与合规 |
| resistance / ESD / EMC / electrical / voltage | CAT-06 电气/EMC |
| reliability / P99 / R95 / sample size / GPAT | CAT-07 质量与可靠性 |
| appearance / marking / color / label | CAT-08 外观与标识 |

> ⚠️ 上表为指导性规则，优先以原文上下文判断，不强制硬匹配关键词。
> 同一需求可归入多类时，取**最具体**的分类。

**design_target 翻译原则：**
- 从规范原文推导出供应商侧的**设计动作**（"做什么"），不只是复述客户要求
- 例：原文 "No leak at 150 PSI" → 设计目标 "密封界面粗糙度/压缩量/材料硬度满足密封压力要求"
- 若无法推导设计动作（纯性能指标）：`design_target` 填写原文数值目标，`needs_review=true`

**置信度标注：**
- 原文有明确数值 → S1 或 S2（来自规范文本）
- 由 AI 推导设计目标（无原文参数支撑）→ S5，`needs_review=true`, `review_reason="low_confidence"`
```

**Step 4: 补充 Step 3 — n07 反馈处理**

```markdown
### Step 3: n07 DFMEA 反馈（可选，仅第二次运行时执行）

若存在 `artifacts/n07-output.json` 且其中包含 `dfmea_corrections` 字段：

​```python
try:
    n07 = store.read('n07')
    corrections = n07['payload'].get('dfmea_corrections', [])
    if corrections:
        log.step("Step 3: Apply n07 DFMEA corrections")
        drg_version += 1
        for corr in corrections:
            # 找到对应 DRG indicator，更新 design_target
            target_id = corr['drg_indicator_id']
            for cat in categories:
                for ind in cat['indicators']:
                    if ind['id'] == target_id:
                        ind['dfmea_correction'] = {
                            "gap_ref":        corr['gap_ref'],
                            "original_target": ind['design_target'],
                            "revised_target":  corr['revised_target'],
                            "revised_at":      datetime.utcnow().isoformat() + "Z"
                        }
                        ind['design_target'] = corr['revised_target']
                        log.info(f"Updated {target_id} per n07 {corr['gap_ref']}")
except Exception:
    log.info("n07 not available — skipping DFMEA feedback step")
​```
```

**Step 5: 补充 Step 4 — 汇总 + Gap + Close Log**

```markdown
### Step 4: 汇总、Gap 识别、写 Artifact

​```python
log.step("Step 4: Aggregate + gaps + write")

review_items = []
for cat in categories:
    for ind in cat['indicators']:
        if ind.get('needs_review'):
            review_items.append({
                "id":     ind['id'],
                "reason": ind.get('review_reason', 'unknown'),
                "detail": ind.get('conflict', {}).get('detail', '') or "见指标详情"
            })

review_required_count = len(review_items)
conflict_count = sum(1 for ri in review_items if ri['reason'] == 'conflict')

# Gap 识别
gaps = []
if not any(cat['indicators'] for cat in categories):
    gaps.append({
        "rule": "R-02-01",
        "msg": "performance_requirements 为空，未能生成任何 DRG 指标",
        "severity": "error", "assumption": None
    })
if review_required_count > 0:
    gaps.append({
        "rule": "R-02-02",
        "msg": f"{review_required_count} 条指标待工程师审阅（描述性/冲突/低置信度）",
        "severity": "warning", "assumption": None
    })
if conflict_count > 0:
    gaps.append({
        "rule": "R-02-03",
        "msg": f"{conflict_count} 处来源冲突未解决",
        "severity": "warning", "assumption": None
    })
cat04 = next((c for c in categories if c['id'] == 'CAT-04'), None)
if geometry and not cat04:
    gaps.append({
        "rule": "R-02-04",
        "msg": "n01 有 geometry 但 CAT-04 尺寸符合性为空，几何约束可能未提取",
        "severity": "warning", "assumption": None
    })

for g in gaps:
    log.gap(g['rule'], g['msg'], g['severity'])
​```

**Artifact 结构：**

​```python
artifact = {
    "node": "n02",
    "project": project_id,
    "status": "ready",
    "produced_at": datetime.utcnow().isoformat() + "Z",
    "confidence_floor": min_confidence,   # 所有指标中最低置信度
    "gaps": gaps,
    "assumptions": [],
    "payload": {
        "drg_version": drg_version,
        "review_required_count": review_required_count,
        "conflict_count": conflict_count,
        "review_items": review_items,
        "categories": categories          # 仅含非空分类
    }
}

store.write('n02', artifact)
log.done(artifact)

from reporter import NodeReport
report = NodeReport(project_path, 'n02')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
​```
```

**Step 6: 补充 Validation 节**

```markdown
## Validation

​```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n02')
p = a['payload']

assert a['status'] == 'ready'
assert p.get('categories'), "categories empty — no DRG indicators generated"
assert isinstance(p['categories'], list)

total = sum(len(c.get('indicators', [])) for c in p['categories'])
assert total > 0, "zero indicators"

# 每条 indicator 必须有必填字段
for cat in p['categories']:
    assert cat.get('indicators'), f"empty category {cat['id']}"
    for ind in cat['indicators']:
        assert ind.get('id'),              f"indicator missing id"
        assert ind.get('parameter'),       f"indicator {ind['id']} missing parameter"
        assert ind.get('source_n01'),      f"indicator {ind['id']} missing source_n01"
        assert 'needs_review' in ind,      f"indicator {ind['id']} missing needs_review"
        assert 'quantified' in ind,        f"indicator {ind['id']} missing quantified"

# review_items 与 needs_review 数量一致
review_in_indicators = sum(
    1 for cat in p['categories']
    for ind in cat['indicators']
    if ind.get('needs_review')
)
assert p['review_required_count'] == review_in_indicators, \
    f"review_required_count mismatch: {p['review_required_count']} vs {review_in_indicators}"

# 无空分类
for cat in p['categories']:
    assert cat.get('indicators'), f"empty category {cat['id']} should not be in output"

gap_rules = [g['rule'] for g in a.get('gaps', [])]
if review_in_indicators > 0:
    assert 'R-02-02' in gap_rules, "R-02-02 missing for review items"

print(f"✓ n02 valid")
print(f"  DRG 指标: {total} 条 ({len(p['categories'])} 类)")
print(f"  待审阅: {p['review_required_count']} | 冲突: {p['conflict_count']}")
print(f"  置信度底线: {a['confidence_floor']}")
print(f"  Gaps: {[g['rule'] for g in a.get('gaps', [])]}")
​```
```

**Step 7: 运行不存在路径验证失败（确认 validation 有效）**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
store = ArtifactStore('/tmp/nonexistent')
store.read('n02')
"
```
预期: FileNotFoundError 或 AssertionError

**Step 8: Commit**

```bash
git add .claude/skills/apqp-os/references/n02-requirements.md
git commit -m "feat: add n02-requirements.md — DRG 设计要求指南执行指南"
```

---

## Task 4: 在 FBFS 项目上执行 n02 并验证

**Files:**
- Read: `artifacts/n01-output.json`（FBFS 项目）

**Step 1: 确认 n01 状态**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from orchestrator import cmd_status
"
# 或直接
python3 /home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/orchestrator.py status FBFS
```
预期: n01 ✅ ready

**Step 2: 按 n02-requirements.md 执行节点**

按指南逐步执行：
1. Precondition check
2. Step 1: 读取 n01 payload
3. Step 2: 分类 + 量化（处理 FBFS 的 24 条 performance_requirements + 9 条 SC/CC）
4. Step 3: 检查是否有 n07（无，跳过）
5. Step 4: 写 artifact

**Step 3: 运行 Validation**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
# paste validation script from n02-requirements.md with project_path='FBFS'
"
```
预期: `✓ n02 valid`

**Step 4: 检查 orchestrator status**

```bash
python3 /home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/orchestrator.py status FBFS
```
预期: n01 ✅, n02 ✅, n03 等待

**Step 5: Commit**

```bash
git add FBFS/artifacts/n02-output.json FBFS/reports/ FBFS/logs/
git commit -m "feat: run n02 on FBFS — DRG indicators generated"
```
