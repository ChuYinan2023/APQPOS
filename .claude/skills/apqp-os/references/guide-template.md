# NODE-XX: [English Name]（[中文名]）

**Purpose**: [一句话描述本节点做什么]
**Input**: [上游 artifact(s) + 需要读取的 source_index key]
**Output**: `artifacts/nXX-output.json`
**Type**: auto | mixed | human

---

## Precondition Check

```python
import json, sys
from pathlib import Path

_APQPOS = next(p for p in [Path.cwd()] + list(Path.cwd().parents)
               if (p / '.claude/skills/apqp-os/scripts').exists())
sys.path.insert(0, str(_APQPOS / '.claude/skills/apqp-os/scripts'))
from store import ArtifactStore
from logger import NodeLogger

p = Path('<project_path>')
store = ArtifactStore('<project_path>')

# 检查所有上游依赖（从 network.json 查本节点的非 feedback 入边）
# 替换 upstream_ids 为本节点实际的上游节点列表
upstream_ids = ['nXX', 'nYY']  # ← 按 network.json 填写
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

# 初始化 logger
log = NodeLogger('<project_path>', 'nXX')
log.step("Precondition: upstream artifacts verified")
for uid in upstream_ids:
    log.info(f"{uid}: status={store.get_status(uid)}")
```

---

## Execution Steps (Build Mode)

### Step 1: [读取输入]

```
log.step("Step 1: ...")
```

[描述要读取哪些上游 artifact 字段、source_index 指向的原始文件]

### Step 2: [核心推理/计算]

```
log.step("Step 2: ...")
```

[描述本节点的核心逻辑——AI 推理步骤、计算公式、决策规则]

### Step N-2: 写 artifact

```python
artifact = {
    "node": "nXX",
    "project": "<project_id>",
    "status": "ready",
    "confidence_floor": "SX",
    "gaps": [{"rule": "R-XX-01", "msg": "...", "severity": "warning", "assumption": "..."}],
    "assumptions": [{"id": "A-01", "field": "...", "value": "...", "unit": "...", "confidence": "S4", "rationale": "..."}],
    "payload": { ... }
}
store.write('nXX', artifact)
```

### Step N-1: 关闭日志

```python
log.done(artifact)
```

### Step N: 写报告

```python
from reporter import NodeReport

# AI 根据本次实际执行情况填写，四个小节不可省略
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| — | `上游 artifact` | 描述 |

### 过程中解决的问题

- 无异常（如无问题则写此行）

### 假设与判断

- 无（如无则写此行）

### 对 skill 的改进

- 无（如无则写此行）
"""

report = NodeReport('<project_path>', 'nXX')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Deliverable Generation (条件步骤)

**仅当本节点负责填写某个交付物时执行此步骤。**

在写完 artifact 和 report 之后，检查 n01 的 `deliverables_required` 中是否有 `filled_by_node` 指向本节点的交付物。如果有，逐个生成。

```python
# 检查本节点是否负责任何交付物
# 当前为报价阶段（Phase 0），只生成 SOURCING 阶段的交付物。
# TKO/DV/PV/SOP 阶段的交付物在中标后的对应阶段再生成。
# 从 project.json 读取当前阶段（默认 SOURCING = Phase 0 报价）
import json
proj = json.loads(Path('<project_path>', 'project.json').read_text())
CURRENT_PHASE = proj.get('current_phase', 'SOURCING')
n01 = store.read('n01')
my_deliverables = [d for d in n01['payload'].get('deliverables_required', [])
                   if d.get('filled_by_node') == 'nXX'
                   and d.get('phase', '') == CURRENT_PHASE]
# 如果某个交付物的 phase 跨阶段（如 "SOURCING/TKO"），也包含在内
my_deliverables += [d for d in n01['payload'].get('deliverables_required', [])
                    if d.get('filled_by_node') == 'nXX'
                    and CURRENT_PHASE in d.get('phase', '')
                    and d not in my_deliverables]

if my_deliverables:
    log.step("Deliverable Generation")
    deliverables_dir = Path('<project_path>') / 'artifacts' / 'deliverables'
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    for d in my_deliverables:
        log.info(f"Generating {d['id']}: {d['name']}")

        # 确定模板来源（三级回退）
        template_path = None
        if d.get('template_file'):
            # 1. 客户模板（优先）
            candidate = Path('<project_path>') / d['template_file']
            if candidate.exists():
                template_path = candidate
                log.info(f"  Using customer template: {candidate.name}")
        if not template_path:
            # 2. 公司内部模板（兜底）
            internal = Path('<APQPOS>/.claude/skills/apqp-os/assets/templates') / f"{d['id']}.xlsx"
            if internal.exists():
                template_path = internal
                log.info(f"  Using internal template: {internal.name}")
        if not template_path:
            # 3. 无模板 → 从零生成标准格式
            log.info(f"  No template found — generating standard format")

        # ── 填写模板 ──────────────────────────────────────────────
        # AI 读取模板文件（如果有），理解其结构（sheet 名、列头、预填内容），
        # 然后用本节点 artifact 中的数据填写。
        #
        # 关键规则：
        # - 读取模板时用 Read tool（xlsx/docx），理解每一列/每一行要填什么
        # - 从本节点的 artifact payload 中提取对应数据
        # - 保留模板的格式、公式、样式，只填数据单元格
        # - 如果某个字段数据不足，留空并标注"TBD"
        # - 不要修改模板的结构（不增删行列，除非数据行数超过预留行）
        #
        # 输出路径：artifacts/deliverables/D-XX-<short_name>.xlsx
        output_path = deliverables_dir / f"{d['id']}-{d['name'].replace(' ','_')[:30]}.xlsx"

        # [AI 在此处实际执行模板填写]
        # 使用 openpyxl 读模板 → 填数据 → 写输出文件

        # 更新 n01 的 deliverable 条目
        d['output_file'] = str(output_path.relative_to(Path('<project_path>')))
        log.info(f"  → {output_path.name}")

    # 写回 n01（更新 output_file 字段）
    store.write('n01', n01)
    log.info(f"Deliverables generated: {len(my_deliverables)} files")
```

**此步骤不在 guide 的 Execution Steps 中——它是模板级的通用逻辑，所有节点共享。**
节点 guide 不需要写交付物生成代码，只需要在 n01 的 `filled_by_node` 中被正确引用即可。

**三级模板回退**：
1. 客户模板（n01 提取的 `template_file`）→ 保持客户格式
2. 公司内部模板（`assets/templates/D-XX.xlsx`）→ 公司标准格式
3. 无模板 → AI 生成标准表格（最后手段）

**Optimize 模式下也要重新生成交付物**——因为数据变了，填写的内容也要更新。

---

## Optimize Mode

当用户提供了更精确的数据（替换 S4/S5 假设为 S1/S2 实测值）时：

1. 读取现有 `artifacts/nXX-output.json`
2. 初始化 logger，所有 step 标题加 `[Optimize]` 前缀
3. 识别哪些字段被更新（对比新数据 vs 现有 assumptions）
4. 仅更新受影响的字段，保留未变化的部分
5. 重新计算 `confidence_floor`（可能从 S4 升到 S1）
6. 从 `gaps` 和 `assumptions` 中移除已解决的条目
7. 写回 artifact → 关闭日志 → 写报告（同 Build 的 Step N-2/N-1/N）
8. 运行 Validation

### 何时退回 Build 模式

以下情况说明变更超出了局部更新的范围，必须全量重跑：

- payload 中**新增或删除了顶层 list 条目**（如 BOM 多了一个零件、DFMEA 多了一个失效模式）
- 上游节点的 **payload 结构发生变化**（新增/删除了字段 key）
- 本节点的 **核心输入来源变了**（如从 CTS PPTX 推导改为 3D 模型实测）
- `confidence_floor` 从 S1/S2 **降级**到 S4/S5（说明数据质量退化，需要重新审视全部逻辑）

如果不确定，选择 Build — 全量重跑比漏更新安全。

---

## Review Mode

仅检查现有 artifact 质量，不修改任何文件：

1. 读取 `artifacts/nXX-output.json`
2. 运行下方 Validation 检查
3. 统计：gaps 数量（按 severity）、assumptions 数量、confidence_floor
4. 输出质量摘要，不写 artifact

---

## Validation

```python
# 在 Build/Optimize 完成后运行
artifact = store.read('nXX')
p = artifact.get('payload', {})

# 1. 必填字段检查
assert artifact.get('status') in ('ready', 'done', 'waiting_human'), "status 无效"
assert artifact.get('confidence_floor'), "confidence_floor 未设置"

# 2. 节点特有校验（按实际需求填写）
# assert len(p.get('some_field', [])) > 0, "some_field 为空"

# 3. gaps 完整性：每个 gap 必须有 rule + msg + severity
for g in artifact.get('gaps', []):
    assert g.get('rule') and g.get('msg') and g.get('severity'), \
        f"gap 格式不完整: {g}"

print(f"✓ nXX validation passed — confidence_floor: {artifact['confidence_floor']}")
```
