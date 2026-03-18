# APQP OS — Skill 架构设计

**版本：** 0.1 草稿
**日期：** 2026-03-11
**范围：** 面向多产品、多客户的汽车 Tier 1 报价系统

---

## 一、核心设计原则

### 1.1 APQP 流程是固定的，产品是未知的

- 18 个节点的 DAG 拓扑对所有零部件相同
- 产品知识不预先配置，由 n01→n02 从客户文件动态提取
- DRG 表是每个项目的"动态产品规格"，所有下游节点以它为验证基准

### 1.2 AI 做判断，Python 做确定性工作

| AI (SKILL.md prompt) | Python (.py script) |
|---|---|
| 理解文档、提取字段 | 读写制品文件 |
| 推断失效模式 | 检查前置条件（文件存在性） |
| 生成工艺路线候选 | 确定性规则验证（数量对齐、字段完备） |
| 判断 Make/Buy | 数学计算（RC、节拍、用量） |
| 解读规范条款 | DAG 调度顺序 |

### 1.3 "Ready ≠ Complete，Ready = 状态已知"

节点不因信息不完整而阻断，而是：
- 标注信息缺口（gap）
- 降低置信度（S1→S5）
- 记录假设（assumption）
- 继续推进，在报价文件中显式说明

### 1.4 置信度体系 S1–S5

| 级别 | 来源 | 含义 |
|---|---|---|
| S1 | 客户文件 / 法规 | 硬性要求，不可假设替代 |
| S2 | 物理计算 | 几何推导，数学确定 |
| S3 | 历史数据 | 本公司历史库 |
| S4 | 行业标准假设 | B2 基准值 |
| S5 | AI 推断 | 无依据，必须标注待验证 |

---

## 二、目录结构

```
apqp-platform/
│
├── core/                          # 平台基础设施，产品无关
│   ├── store.py                   # 制品仓库（读写 artifacts/ 下的 JSON）
│   ├── runner.py                  # 单节点执行器
│   └── orchestrator.py            # DAG 调度器
│
├── network.json                   # DAG 定义（节点 + 边 + 依赖关系）
│
├── skills/                        # 18 个节点，每个一个文件夹
│   ├── n01-requirements/
│   ├── n02-drg/
│   ├── n03-3d-model/
│   ├── n04-bom/
│   ├── n05-material-selection/
│   ├── n06-quantity-calc/
│   ├── n07-dfmea/
│   ├── n08-process-route/
│   ├── n09-dvpr/
│   ├── n10-pfd/
│   ├── n11-material-cost/
│   ├── n12-conversion-cost/
│   ├── n13-capacity/
│   ├── n14-project-plan/
│   ├── n15-edd/
│   ├── n16-rc/
│   ├── n17-nrc/
│   └── n18-quotation/
│
└── projects/                      # 每个询价一个文件夹
    └── FC00SAA78530-KP1/
        ├── project.json
        ├── inputs/                # 客户原始文件
        └── artifacts/             # 运行时制品（JSON）
```

---

## 三、单个 Skill 内部结构

```
skills/n02-drg/
├── SKILL.md                       # 节点说明 + prompt 模板 + 输出格式
├── scripts/
│   ├── precondition.py            # 检查前置制品是否就绪
│   └── validate.py                # 一致性 + 完备性验证
└── references/
    └── rules.md                   # 人类可读的验证规则（可独立维护）
```

### 3.1 SKILL.md 结构

```yaml
---
name: n02-drg
description: |
  NODE-02 DRG 设计要求指南。
  将客户规范条款翻译为量化工程指标表。
  输入：n01 解析字段表。输出：DRG 量化指标表。
inputs:
  required: [n01-output.json]
  optional: [n07-feedback.json]
outputs: [n02-output.json]
---

## 执行步骤

1. 运行 scripts/precondition.py
2. 运行 scripts/validate.py
3. 用以下 prompt 调用 AI

## Prompt 模板

你是汽车零部件工程师。以下是从客户文件解析的字段表：
{n01_output}

将每条要求转化为量化工程指标，输出格式见下方 Schema。
无法量化的条款：置信度降为 S4/S5，记录原因。

## 输出 Schema

{
  "node": "n02",
  "status": "ready",
  "gaps": [],
  "rows": [
    {
      "indicator_id": "DRG-001",
      "source": "PF.90197 §5.3",
      "value": "≥36 bar @ 23°C",
      "confidence": "S1",
      "note": ""
    }
  ]
}
```

### 3.2 precondition.py

```python
import json, sys
from pathlib import Path

def check(artifact_dir):
    required = ["n01-output.json"]
    blocking = [f for f in required if not (Path(artifact_dir) / f).exists()]
    missing  = []
    for f in required:
        p = Path(artifact_dir) / f
        if p.exists():
            d = json.loads(p.read_text())
            if d.get("status") != "ready":
                missing.append(f"{f}: status={d.get('status')}")
    return {"ready": not blocking, "missing": missing, "blocking": blocking}

if __name__ == "__main__":
    result = check(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ready"] else 1)
```

### 3.3 validate.py（通用覆盖率检查）

```python
import json
from pathlib import Path

def validate_drg_coverage(node_outputs, drg_rows, drg_ref_field="drg_ref"):
    """
    通用验证：检查本节点输出是否覆盖了所有 DRG 指标
    所有下游节点（n07/n09/n08等）都调用此函数
    """
    covered = {item[drg_ref_field] for item in node_outputs if drg_ref_field in item}
    gaps = []
    for row in drg_rows:
        if row["indicator_id"] not in covered:
            gaps.append({
                "drg_ref": row["indicator_id"],
                "requirement": row["requirement"],
                "severity": "warning" if row["confidence"] in ["S3","S4","S5"] else "error"
            })
    return gaps
```

### 3.4 references/rules.md（人类维护，不是代码）

```markdown
# NODE-02 验证规则

## R-02-01 每条 DRG 指标必须有明确来源条款
- 检查：source 字段不为空
- 不满足：置信度降为 S4，标注"来源待确认"

## R-02-02 年需求量
- 检查：n01 输出中 annual_volume 存在且为正整数
- 不满足：节拍计算使用 4000小时/年默认值，置信度 S4

## R-02-03 S1 指标不得被 AI 假设替代
- 检查：confidence=S1 的指标必须能追溯到客户文件原文
- 不满足：阻断，要求工程师确认
```

---

## 四、制品（Artifact）格式规范

每个制品 JSON 都有统一的 envelope：

```json
{
  "node": "n02",
  "project": "FC00SAA78530-KP1",
  "status": "ready",
  "produced_at": "2026-03-11T10:30:00Z",
  "confidence_floor": "S1",
  "gaps": [
    {
      "rule": "R-02-02",
      "msg": "年需求量缺失，节拍使用默认值",
      "severity": "warning",
      "assumption": "annual_volume=50000，置信度S4"
    }
  ],
  "assumptions": ["annual_volume 使用行业基准 50000件/年"],
  "payload": {
    // 节点特定数据
  }
}
```

`status` 的取值：

| 值 | 含义 |
|---|---|
| `pending` | 前置条件未满足 |
| `blocked` | 硬性阻断（如3D文件未到） |
| `ready` | 可用（可能含缺口） |
| `waiting_human` | 需要人工输入（如n03 3D数模解析） |
| `done` | 已被下游消费 |

---

## 五、DAG 定义（network.json）

```json
{
  "nodes": [
    {"id": "n01", "skill": "skills/n01-requirements", "type": "auto"},
    {"id": "n02", "skill": "skills/n02-drg",          "type": "auto"},
    {"id": "n03", "skill": "skills/n03-3d-model",     "type": "human"},
    {"id": "n04", "skill": "skills/n04-bom",          "type": "mixed"},
    {"id": "n05", "skill": "skills/n05-material",     "type": "mixed"},
    {"id": "n06", "skill": "skills/n06-quantity",     "type": "auto"},
    {"id": "n07", "skill": "skills/n07-dfmea",        "type": "mixed"},
    {"id": "n08", "skill": "skills/n08-process",      "type": "mixed"},
    {"id": "n09", "skill": "skills/n09-dvpr",         "type": "mixed"},
    {"id": "n10", "skill": "skills/n10-pfd",          "type": "mixed"},
    {"id": "n11", "skill": "skills/n11-mat-cost",     "type": "auto"},
    {"id": "n12", "skill": "skills/n12-conv-cost",    "type": "auto"},
    {"id": "n13", "skill": "skills/n13-capacity",     "type": "mixed"},
    {"id": "n14", "skill": "skills/n14-project-plan", "type": "mixed"},
    {"id": "n15", "skill": "skills/n15-edd",          "type": "mixed"},
    {"id": "n16", "skill": "skills/n16-rc",           "type": "auto"},
    {"id": "n17", "skill": "skills/n17-nrc",          "type": "auto"},
    {"id": "n18", "skill": "skills/n18-quotation",    "type": "human"}
  ],
  "edges": [
    {"from": "n01", "to": "n02", "type": "main"},
    {"from": "n02", "to": "n03", "type": "main"},
    {"from": "n03", "to": "n04", "type": "normal"},
    {"from": "n03", "to": "n05", "type": "normal"},
    {"from": "n03", "to": "n06", "type": "normal"},
    {"from": "n03", "to": "n07", "type": "normal"},
    {"from": "n03", "to": "n08", "type": "normal"},
    {"from": "n04", "to": "n05", "type": "secondary"},
    {"from": "n04", "to": "n06", "type": "secondary"},
    {"from": "n04", "to": "n10", "type": "secondary"},
    {"from": "n02", "to": "n07", "type": "normal"},
    {"from": "n02", "to": "n09", "type": "normal"},
    {"from": "n07", "to": "n09", "type": "normal"},
    {"from": "n07", "to": "n08", "type": "secondary"},
    {"from": "n07", "to": "n02", "type": "feedback"},
    {"from": "n08", "to": "n10", "type": "normal"},
    {"from": "n08", "to": "n11", "type": "secondary"},
    {"from": "n08", "to": "n12", "type": "normal"},
    {"from": "n08", "to": "n13", "type": "normal"},
    {"from": "n05", "to": "n11", "type": "normal"},
    {"from": "n06", "to": "n11", "type": "normal"},
    {"from": "n09", "to": "n15", "type": "normal"},
    {"from": "n10", "to": "n13", "type": "normal"},
    {"from": "n11", "to": "n16", "type": "normal"},
    {"from": "n12", "to": "n16", "type": "normal"},
    {"from": "n13", "to": "n17", "type": "normal"},
    {"from": "n14", "to": "n15", "type": "normal"},
    {"from": "n15", "to": "n17", "type": "normal"},
    {"from": "n16", "to": "n18", "type": "normal"},
    {"from": "n17", "to": "n18", "type": "normal"},
    {"from": "n01", "to": "n18", "type": "secondary"},
    {"from": "n01", "to": "n14", "type": "secondary"},
    {"from": "n01", "to": "n09", "type": "secondary"}
  ],
  "blocking_inputs": [
    {"node": "n03", "source": "ext-3d", "reason": "3D文件必须从客户Teamcenter获取"}
  ]
}
```

---

## 六、core/orchestrator.py 调度逻辑

```python
import json
from pathlib import Path
from core.store import ArtifactStore
from core.runner import SkillRunner

class Orchestrator:
    def __init__(self, project_path):
        self.project = json.loads((Path(project_path) / "project.json").read_text())
        self.store   = ArtifactStore(Path(project_path) / "artifacts")
        self.network = json.loads(Path("network.json").read_text())
        self.runner  = SkillRunner(self.store)

    def get_ready_nodes(self):
        """返回所有前置条件已满足、尚未完成的节点"""
        done    = self.store.list_done()
        all_ids = {n["id"] for n in self.network["nodes"]}
        ready   = []
        for node in self.network["nodes"]:
            if node["id"] in done:
                continue
            deps = [e["from"] for e in self.network["edges"] if e["to"] == node["id"]]
            if all(d in done or d.startswith("ext-") for d in deps):
                ready.append(node)
        return ready

    def run(self):
        while True:
            ready = self.get_ready_nodes()
            if not ready:
                break
            for node in ready:
                if node["type"] == "human":
                    print(f"⏸  {node['id']} 需要人工操作，跳过（状态设为 waiting_human）")
                    self.store.set_status(node["id"], "waiting_human")
                    continue
                result = self.runner.run(node, self.project)
                print(f"✓  {node['id']} 完成，置信度 {result['confidence_floor']}")
                if result["gaps"]:
                    print(f"   ⚠ {len(result['gaps'])} 个缺口")
```

---

## 七、产品无关性的实现方式

### n01 发现产品身份

n01 的 prompt 中包含：
- "识别这是什么类别的零部件（流体管路 / 连接件 / 传感器 / 结构件…）"
- "列出所有引用的客户规范编号"
- "标注所有未提供但通常必需的信息"

n01 的输出会包含 `product_category` 和 `applicable_standards`，但这些字段**不驱动流程分支**——流程始终一样，只是 AI 在后续节点中参考这个上下文。

### DRG 是所有下游的验证基准

所有下游节点的 validate.py 都调用同一个函数：

```python
gaps = validate_drg_coverage(my_outputs, drg["rows"])
```

不管产品是什么，只要 DRG 表存在，验证逻辑就能运行。

---

## 八、人工节点的挂起与恢复

n03（3D数模解析）和 n18（报价）是人工节点，需要暂停等待：

```
orchestrator 遇到 human 节点
    → 设状态为 waiting_human
    → 输出结构化表单（需要录入的字段列表）
    → 人工填写后调用 resume 命令
    → orchestrator 读取人工输入，继续后续节点
```

人工输入格式与 AI 输出格式相同（同一个 artifact JSON schema），下游节点无法区分来源。

---

## 九、项目 project.json

```json
{
  "id": "FC00SAA78530-KP1",
  "customer": "Stellantis",
  "rfq_files": [
    "inputs/KP1 Fuel line damper description.pptx",
    "inputs/SSTS KP1 Fuel line.xlsx",
    "inputs/PF.90197.pdf",
    "inputs/PF.90298_QC接头要求.pdf"
  ],
  "known_gaps": {
    "annual_volume": null,
    "sop_date": null,
    "3d_model_available": false
  },
  "created_at": "2026-03-11"
}
```

---

## 十、开发路线

### 阶段一：打通端到端管道（2周）

目标：`n01 → n02 → n18` 能跑通，制品能读写，缺口能标注

- `core/store.py`
- `core/runner.py`
- `core/orchestrator.py`（简化版，只跑线性序列）
- `skills/n01-requirements/`（完整）
- `skills/n02-drg/`（完整）
- `skills/n18-quotation/`（只汇总已有制品 + 缺口清单）

### 阶段二：加入第二个产品类型（1周）

目标：用一个完全不同的零部件（如快插接头）跑 n01→n02，验证产品无关性

- 如果需要改动 skill-templates，说明抽象还不够干净
- 此阶段暴露的问题比第一阶段更有价值

### 阶段三：补全技术主干（3周）

按依赖顺序：`n03 → n04 → n05 → n06 → n07 → n08`

- n03 优先（整条技术主干的唯一几何来源）
- n07（DFMEA）是人工工作量最大的节点，先出框架

### 阶段四：成本计算层（2周）

`n09 → n10 → n11 → n12 → n13 → n14 → n15 → n16 → n17`

- n11/n12/n16/n17 是纯计算节点，最简单
- n13/n14/n15 需要 B1 数据库接口

---

## 十一、未决设计问题

| 问题 | 当前状态 | 影响 |
|---|---|---|
| AI 调用方式（直接 API / Claude Code agent） | 未决 | 影响 runner.py 实现 |
| B1 数据库形式（JSON文件 / SQLite / 外部系统） | 未决 | 影响 n05/n08/n12/n13 |
| 人工表单的 UI（命令行 / Web） | 未决 | 影响 n03/n18 |
| 多用户并发项目 | 未决 | 影响 store.py 设计 |
| 置信度传播规则（下游继承最低值？加权？） | 未决 | 影响 store.py 和报价输出 |
