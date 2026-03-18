---
name: apqp-os
description: |
  APQP Operating System for automotive Tier 1 suppliers. Orchestrates an 18-node DAG for Phase 0
  (RFQ/quotation preparation): document parsing, requirement extraction, DFMEA, process routing,
  cost calculation, and quotation generation.

  Trigger when: user mentions APQP, RFQ, quotation/报价准备/询价, automotive supplier workflow,
  initializing a project, or running any node (n01–n18). Also trigger when user uploads customer
  files (PDF/DOCX/XLSX/PPTX) in an automotive context.
---

# APQP OS

## Command Routing

Parse `$ARGUMENTS` to determine the action. Format: `<command> [node_id] <project_path> [options]`

| Command | Usage | Action |
|---------|-------|--------|
| **status** | `/apqp-os status <project>` | Run `orchestrator.py status <project>` — show DAG progress + data quality |
| **init** | `/apqp-os init <project> --customer <OEM>` | Run `orchestrator.py init` — create project directory |
| **run** | `/apqp-os run <node> <project>` | Build mode — load guide, execute, write artifact/log/report |
| **optimize** | `/apqp-os optimize <node> <project>` + user note | Optimize mode — load guide Optimize section, update artifact, run affected |
| **review** | `/apqp-os review <node> <project>` | Review mode — load guide Validation, report quality, do NOT modify |
| **affected** | `/apqp-os affected <node> <project>` | Run `orchestrator.py affected` — show downstream impact |

If no command is recognized, infer from context:
- User mentions a node ID (n01–n18) + project path → `run`
- User says "status" or asks about progress → `status`
- User says "update/补充/客户确认" → `optimize`
- User says "check/检查/审查" → `review`

## Layout

User's project directory (anywhere on disk):
```
<project>/
├── project.json         # project metadata
├── inputs/              # customer RFQ files (PDF/DOCX/XLSX/PPTX)
├── artifacts/           # runtime outputs: nXX-output.json
├── logs/                # execution trace: nXX-YYYYMMDD-HHMMSS.md
└── reports/             # human-readable completion reports: nXX-report-YYYYMMDD-HHMMSS.md
```

Skill infrastructure (read-only):
- Scripts: `<APQPOS>/.claude/skills/apqp-os/scripts/`
- Node guides: `<APQPOS>/.claude/skills/apqp-os/references/nXX-*.md`
- DAG definition: `<APQPOS>/.claude/skills/apqp-os/references/network.json`

Where `<APQPOS>` = `/home/chu2026/Documents/APQPOS`

## Workflow Modes

The `run`, `optimize`, `review` commands map to three execution modes:

- **run** (Build): First execution. `artifacts/nXX-output.json` does not exist → full guide execution.
- **optimize**: Artifact exists + user provides new data → load guide's Optimize Mode, update fields, run `affected` for downstream cascade.
- **review**: Artifact exists → run Validation only, report quality, do NOT modify.

## Node Execution Pattern

For every ready node (applies to Build and Optimize; Review skips steps 4–7):

1. **Load guide** — read `references/nXX-<name>.md` for this node
2. **Precondition** — run the Python snippet from the guide (checks upstream artifacts)
3. **Start logger** — instantiate NodeLogger at the very beginning of execution
4. **Execute** — follow the AI reasoning steps in the guide, calling log methods throughout
5. **Write artifact** — use store.py (see below)
6. **Close log** — call `log.done(artifact)` after writing artifact
7. **Write report** — call `NodeReport.write(artifact)` and `print_summary(artifact)` (see below)
8. **Generate deliverables (mandatory check)** — after EVERY node, check n01 `deliverables_required` for entries where `filled_by_node` matches this node AND `phase` matches `project.json.current_phase`. If found: read the customer template (or generate standard format), fill with this node's artifact data, save to `artifacts/deliverables/D-XX-name.xlsx`, update n01's `output_file` field. See guide-template.md § Deliverable Generation for full logic. **This step applies even if the node guide does not mention it.**
9. **Validate** — run the validation snippet from the guide

### Execution Logging

Every node must log its execution for traceability. Log files are written to `<project>/logs/`.

```python
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from logger import NodeLogger

log = NodeLogger('<project_path>', 'nXX')   # creates logs/nXX-YYYYMMDD-HHMMSS.md

log.step("Step 1: Read input files")        # major step header
log.info("Found 6 files in inputs/")        # informational
log.file("SSTS.xlsx", "采购技术总要求", "L0")  # file classification
log.embed("SSTS.xlsx", ["CTS.docx"], ["ole1.bin"])  # embedding extraction
log.warn("annual_volume not found")         # warning
log.error("SAE J2044 not in file set")      # error
log.gap("R-01-01", "annual_volume missing", "warning", "50000 (S4)")  # gap record

log.done(artifact)   # writes summary table + gaps, closes log
```

The node guide (`references/nXX-*.md`) specifies exactly where to call each log method.

### Writing an Artifact

```python
from store import ArtifactStore

store = ArtifactStore('<project_path>')
artifact = {
    "node": "n01",
    "project": "<project_id>",
    "status": "ready",
    "confidence_floor": "S1",
    "gaps": [],
    "assumptions": [],
    "payload": { ... }
}
store.write('n01', artifact)
log.done(artifact)   # always call after store.write
```

See `references/artifact-schema.md` for the full envelope spec.

### Writing the Completion Report

```python
from reporter import NodeReport
# execution_summary 必须包含四个小节：读取的文件、过程中解决的问题、假设与判断、对 skill 的改进
report = NodeReport('<project_path>', 'nXX')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

## Node Reference Files

| Node | Name | Guide | Type |
|------|------|-------|------|
| n01 | Requirements Parser | references/n01-requirements.md | auto |
| n02 | DRG Indicators | references/n02-requirements.md | auto |
| n03 | 3D Model | references/n03-requirements.md | **human** |
| n04 | BOM | references/n04-requirements.md | mixed |
| n05 | Material Selection | references/n05-requirements.md | mixed |
| n06 | Quantity Calc | references/n06-requirements.md | auto |
| n07 | DFMEA | references/n07-requirements.md | mixed |
| n08 | Process Route | references/n08-requirements.md | mixed |
| n09 | DVPR | references/n09-requirements.md | mixed |
| n10 | PFD | references/n10-requirements.md | mixed |
| n11 | Material Cost | references/n11-requirements.md | auto |
| n12 | Conversion Cost | references/n12-requirements.md | auto |
| n13 | Capacity | references/n13-requirements.md | mixed |
| n14 | Project Plan | references/n14-requirements.md | mixed |
| n15 | EDD | references/n15-requirements.md | mixed |
| n16 | RC | references/n16-requirements.md | auto |
| n17 | NRC | references/n17-requirements.md | auto |
| n18 | Quotation | references/n18-requirements.md | **human** |

Load the guide before executing any node. Guides follow the template in `references/guide-template.md`.

## Human Node HALT

For `type: human` nodes (n03, n18), output the required fields and pause:

```
⏸ HALT — n03 requires human input
Provide the following fields then say "continue":
- [ ] outer_diameter (mm)
- [ ] wall_thickness (mm)
- [ ] total_length (mm)
- [ ] connector_type
```

After user provides data, write artifact JSON manually and continue.

## Confidence Levels

| Level | Source | Rule |
|-------|--------|------|
| S1 | Client doc / regulation | Hard — no assumption allowed |
| S2 | Physics / geometry | Math-derived |
| S3 | Company history | From internal JSON database |
| S4 | Industry baseline | Must document assumption |
| S5 | AI inference | Must flag as "待验证" |

`confidence_floor` = lowest level across all outputs in this node.

## Proactive Triggers

Alert the user automatically when any of these conditions are detected:

- **上游 error gap 未修复**: 上游 artifact 的 gaps 中存在 `severity=error` → 阻断本节点执行，提示先修复上游
- **n03 扇出警告**: n03 (3D Model) 仍为 pending 但用户要求执行 n04–n08 → 警告"n03 是扇出枢纽，跳过将导致大量 S5 假设"
- **覆盖已有结果**: 目标节点已有 artifact 但用户要求 Build 模式 → 确认"将覆盖现有结果"并运行 `orchestrator.py affected` 提示级联影响
- **OEM 未识别**: `project.json` 中 customer 为空 → 提醒"无法加载 OEM 特定规则，使用通用配置"

## Validation Summary

| Node | 完成标准 | 验证方式 |
|------|---------|---------|
| n01 | extraction_matrix 通过 + source_index 完整 | `python3 extraction_matrix.py artifacts/n01-output.json` |
| n02 | DRG 指标已提取 + 全部有 source_doc | guide 内 Validation 段 |
| n03 | geometry 四维完整 + connector_type 非空 | guide 内 Validation 段 |
| n04–n18 | artifact schema 校验 + gaps 已记录 + confidence_floor 已设置 | guide 内 Validation 段 |
| **通用** | log.done() 已调用 + report 已生成 | 检查 logs/ 和 reports/ 目录 |

## Output Artifacts

| 输入 | 输出 | 位置 |
|------|------|------|
| 用户 RFQ 文件 + 上游 artifacts | 节点结构化数据 | `artifacts/nXX-output.json` |
| 执行过程记录 | 执行日志 | `logs/nXX-YYYYMMDD-HHMMSS.md` |
| artifact 数据摘要 | 人类可读报告 | `reports/nXX-report-YYYYMMDD-HHMMSS.md` |
| extraction_matrix 检查 | 覆盖度报告 | `artifacts/nXX-extraction-coverage.json` (n01) |
