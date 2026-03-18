# n03 3D 数模解析 — 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 n03 节点的 fallback 模式：无 3D 模型时从 n01 geometry + n02 CAT-04 自动聚合组件树和装配接口，生成下游可消费的 artifact。

**Architecture:** n03-requirements.md 作为 AI 执行剧本，复用 logger/store/reporter 脚本库。reporter.py 新增 `_n03_sections()` 方法渲染组件树和装配接口。执行脚本从 n01.geometry 动态识别组件类型，从 n02 CAT-04 补充公差/Cpk。

**Tech Stack:** Python 3.11+，现有 apqp-os scripts (logger, store, reporter)

**设计文档:** `doc/plans/2026-03-14-n03-design.md`

---

## Task 1: 为 reporter.py 新增 `_n03_sections()`

**Files:**
- Modify: `.claude/skills/apqp-os/scripts/reporter.py`

### Step 1: 写失败测试

创建 `/tmp/test_n03_report.py`:

```python
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from reporter import NodeReport

artifact = {
    "node": "n03", "project": "TEST", "status": "ready",
    "confidence_floor": "S1",
    "gaps": [{"rule": "R-03-02", "msg": "No 3D model", "severity": "warning", "assumption": None}],
    "assumptions": [],
    "payload": {
        "geometry_version": 1,
        "has_3d_model": False,
        "completeness_pct": 65,
        "missing_from_3d": ["Routing and bend angles"],
        "components": [
            {
                "id": "COMP-01", "name": "Feed Tube", "type": "tube", "quantity": 1,
                "material_hint": "PA12",
                "dimensions": [
                    {
                        "id": "DIM-C1-001", "parameter": "OD", "nominal": 8.0,
                        "tolerance_plus": 0.1, "tolerance_minus": 0.1,
                        "unit": "mm", "cpk_target": 1.67, "gdt_symbol": None,
                        "source_drg": "IND-CAT-04-034",
                        "source_n01": "geometry.feed_line_od_mm",
                        "confidence": "S1", "needs_review": False
                    }
                ],
                "missing_dimensions": ["length", "bend_profile"]
            }
        ],
        "assembly_interfaces": [
            {
                "id": "INTF-01", "name": "Feed tube → Engine HP port",
                "type": "quick_connect",
                "components": ["COMP-01", "COMP-04"],
                "mating_dimensions": [
                    {"parameter": "End-form OD", "nominal": 10.6,
                     "tolerance": "±0.2", "unit": "mm", "confidence": "S1"}
                ],
                "sc_cc_refs": ["SC⊗ Leak-tightness"],
                "needs_review": False
            }
        ]
    }
}

import tempfile
with tempfile.TemporaryDirectory() as tmp:
    r = NodeReport(tmp, 'n03')
    path = r.write(artifact)
    text = path.read_text()

    assert "3D 数模解析" in text,  "节点名称缺失"
    assert "COMP-01" in text,      "组件 ID 缺失"
    assert "INTF-01" in text,      "接口 ID 缺失"
    assert "完整度" in text,        "完整度缺失"
    assert "fallback" in text,     "3D 模型 fallback 状态缺失"

print("✓ n03 report sections work")
```

### Step 2: 运行确认失败

```bash
python3 /tmp/test_n03_report.py
```

预期: `AssertionError: 节点名称缺失` 或 `COMP-01 缺失`（走 `_generic_payload_section`）

### Step 3: 在 `_build()` 中添加 n03 分支

在 reporter.py `_build()` 的 node-specific sections 处，将：

```python
        if self.node_id == "n01":
            L += self._n01_sections(p, artifact)
        elif self.node_id == "n02":
            L += self._n02_sections(p, artifact)
        else:
            L += self._generic_payload_section(p)
```

改为：

```python
        if self.node_id == "n01":
            L += self._n01_sections(p, artifact)
        elif self.node_id == "n02":
            L += self._n02_sections(p, artifact)
        elif self.node_id == "n03":
            L += self._n03_sections(p, artifact)
        else:
            L += self._generic_payload_section(p)
```

### Step 4: 在 `print_summary()` 中添加 n03 专属摘要

在 `print_summary()` 的 n02 专属摘要块之后（`if self.node_id == "n02":` 块后），添加：

```python
        # n03 专属摘要
        if self.node_id == "n03":
            comps = p.get("components", [])
            intf = p.get("assembly_interfaces", [])
            pct = p.get("completeness_pct", 0)
            has_3d = p.get("has_3d_model", False)
            model_flag = "✓ 有" if has_3d else "⚠️ fallback（无 3D 模型）"
            print(f"    组件: {len(comps)} | 接口: {len(intf)} | 完整度: {pct}% | 3D 模型: {model_flag}")
```

### Step 5: 在文件末尾追加 `_n03_sections()` 方法

在 `_n02_sections()` 之后、`_generic_payload_section()` 之前插入：

```python
    def _n03_sections(self, p: dict, artifact: dict) -> list[str]:
        L = []

        # ── 几何总览 ─────────────────────────────────────────────────────
        version = p.get("geometry_version", 1)
        has_3d = p.get("has_3d_model", False)
        completeness = p.get("completeness_pct", 0)
        components = p.get("components", [])
        interfaces = p.get("assembly_interfaces", [])
        model_str = "✅ 有" if has_3d else "⚠️ 无（fallback 模式）"

        L += [
            "## 几何模型总览",
            "",
            "| 版本 | 3D 模型 | 完整度 | 组件数 | 接口数 |",
            "|------|--------|------|------|------|",
            f"| v{version} | {model_str} | {completeness}% | {len(components)} | {len(interfaces)} |",
            "",
        ]

        # ── 待 3D 模型补充的缺口 ──────────────────────────────────────────
        missing = p.get("missing_from_3d", [])
        if missing:
            L += ["## ⚠️ 待 3D 模型补充", ""]
            for m in missing:
                L.append(f"- {m}")
            L.append("")

        # ── 组件清单 ─────────────────────────────────────────────────────
        if components:
            L += ["## 组件清单", ""]
            L.append("| ID | 名称 | 类型 | 数量 | 材料提示 | 已知尺寸 | 缺失尺寸 |")
            L.append("|----|------|------|------|---------|--------|--------|")
            for c in components:
                dim_count = len(c.get("dimensions", []))
                missing_count = len(c.get("missing_dimensions", []))
                missing_flag = f"⚠️ {missing_count}" if missing_count else "✓"
                mat = (c.get("material_hint") or "")[:30]
                L.append(
                    f"| `{c.get('id', '')}` | {c.get('name', '')} | {c.get('type', '')} "
                    f"| {c.get('quantity', 1)} | {mat} | {dim_count} | {missing_flag} |"
                )
            L.append("")

            # ── 组件尺寸明细 ──────────────────────────────────────────────
            L += ["## 组件尺寸明细", ""]
            for c in components:
                dims = c.get("dimensions", [])
                if not dims:
                    continue
                L += [f"### {c.get('id', '')} — {c.get('name', '')}", ""]
                L.append("| 参数 | 标称 | 公差+ | 公差- | 单位 | Cpk | 置信度 | 审阅 |")
                L.append("|------|------|-------|-------|------|-----|------|------|")
                for d in dims:
                    review = "⚠️" if d.get("needs_review") else "✓"
                    cpk = d.get("cpk_target") or "—"
                    t_plus = d.get("tolerance_plus")
                    t_minus = d.get("tolerance_minus")
                    t_plus_str = f"+{t_plus}" if t_plus is not None else "—"
                    t_minus_str = f"-{t_minus}" if t_minus is not None else "—"
                    L.append(
                        f"| {d.get('parameter', '')} | {d.get('nominal', '')} "
                        f"| {t_plus_str} | {t_minus_str} | {d.get('unit', '')} "
                        f"| {cpk} | {d.get('confidence', '')} | {review} |"
                    )
                L.append("")

        # ── 装配接口 ─────────────────────────────────────────────────────
        if interfaces:
            L += ["## 装配接口", ""]
            L.append("| ID | 名称 | 类型 | 关联组件 | SC/CC | 审阅 |")
            L.append("|----|------|------|---------|------|------|")
            for intf in interfaces:
                review = "⚠️" if intf.get("needs_review") else "✓"
                comps_str = ", ".join(intf.get("components", []))
                sc_str = ("; ".join(intf.get("sc_cc_refs", [])))[:40] or "—"
                L.append(
                    f"| `{intf.get('id', '')}` | {intf.get('name', '')} | {intf.get('type', '')} "
                    f"| {comps_str} | {sc_str} | {review} |"
                )
            L.append("")

        return L
```

### Step 6: 运行测试确认通过

```bash
python3 /tmp/test_n03_report.py
```

预期: `✓ n03 report sections work`

### Step 7: Commit

```bash
cd /home/chu2026/Documents/APQPOS
git add .claude/skills/apqp-os/scripts/reporter.py
git commit -m "feat: add n03 geometry report sections to reporter.py"
```

---

## Task 2: 编写 n03-requirements.md

**Files:**
- Create: `.claude/skills/apqp-os/references/n03-requirements.md`

### Step 1: 创建文件

创建 `.claude/skills/apqp-os/references/n03-requirements.md`，内容如下（完整写入）：

````markdown
# NODE-03: 3D 数模解析（3D Model Parser）

**Purpose**: 从 n01 geometry 和 n02 CAT-04 聚合组件树和装配接口，供 n04–n08 消费。
无 3D 模型时以 fallback 模式运行；3D 模型到来时增量更新（geometry_version + 1）。
**Input**: `artifacts/n01-output.json`, `artifacts/n02-output.json`
**Output**: `artifacts/n03-output.json`
**Type**: auto-fallback（无 3D 模型时全自动；有 3D 模型时需人工触发增量更新）

---

## Precondition Check

```python
import sys, json
from pathlib import Path
from datetime import datetime, timezone

project_path = Path('<project_path>')
sys.path.insert(0, str(Path('<apqp_os_root>/.claude/skills/apqp-os/scripts')))

from store import ArtifactStore
from logger import NodeLogger
from reporter import NodeReport

store = ArtifactStore(str(project_path))
log = NodeLogger(str(project_path), 'n03')

n01 = store.read('n01')
n02 = store.read('n02')
assert n01['status'] == 'ready', "n01 not ready"
assert n02['status'] == 'ready', "n02 not ready"
assert n01['payload'].get('geometry'), "n01.geometry empty — cannot identify components"

log.step("Precondition: n01 and n02 ready")
```

---

## Step 1: 读取输入字段

```python
log.step("Step 1: Load n01 and n02 fields")

p1 = n01['payload']
geometry      = p1.get('geometry', {})
sc_cc         = p1.get('special_characteristics', [])
material      = p1.get('material_compliance', {})
qc            = p1.get('quick_connector', {})

# n02 CAT-04 indicators（公差 / Cpk 补充来源）
cat04_inds = []
for cat in n02['payload'].get('categories', []):
    if cat['id'] == 'CAT-04':
        cat04_inds = cat.get('indicators', [])
        break

log.info(f"geometry keys: {list(geometry.keys())}")
log.info(f"sc_cc count: {len(sc_cc)}")
log.info(f"CAT-04 indicators: {len(cat04_inds)}")
```

---

## Step 2: 构建组件树

### 2a. 辅助函数

```python
import re

def find_drg(keyword: str) -> dict | None:
    """从 CAT-04 指标中按关键字模糊匹配，返回第一个匹配的 indicator。"""
    kw = keyword.lower()
    for ind in cat04_inds:
        if kw in ind.get('parameter', '').lower():
            return ind
    return None

def parse_tolerance(val_str) -> tuple:
    """解析 '8.0 ± 0.1' 或数字字符串，返回 (nominal, tol_plus, tol_minus)。"""
    if val_str is None:
        return None, None, None
    s = str(val_str).strip()
    if '±' in s:
        parts = s.split('±')
        try:
            nominal = float(parts[0].strip())
            tol = float(parts[1].strip())
            return nominal, tol, tol
        except Exception:
            pass
    try:
        return float(s), None, None
    except Exception:
        return None, None, None

def extract_cpk(drg_ind: dict | None) -> float | None:
    """从 design_target 文本中提取 Cpk 目标值。"""
    if drg_ind is None:
        return None
    m = re.search(r'Cpk\s*[≥>=]\s*([\d.]+)', drg_ind.get('design_target', ''))
    return float(m.group(1)) if m else None

comp_counter = [0]
dim_counter  = [0]

def make_comp_id() -> str:
    comp_counter[0] += 1
    return f"COMP-{comp_counter[0]:02d}"

def make_dim_id(comp_num: int) -> str:
    dim_counter[0] += 1
    return f"DIM-C{comp_num:02d}-{dim_counter[0]:03d}"

def sc_cc_refs_for(*keywords) -> list[str]:
    """返回包含任一关键词的 SC/CC 参数名列表。"""
    refs = []
    for sc in sc_cc:
        param = sc.get('parameter', '').lower()
        for kw in keywords:
            if kw.lower() in param:
                sym = sc.get('symbol', sc.get('type', 'SC'))
                refs.append(f"{sym} {sc.get('parameter', '')}")
                break
    return refs
```

### 2b. 识别管体（tube）

```python
# PSEUDOCODE — AI 执行时内联实现以下逻辑
# 遍历 geometry 的所有键，找出成对出现的 *_od_mm / *_id_mm

# 通用识别规则：
# - geometry 中存在 foo_od_mm 且同时存在 foo_id_mm → 识别为一根管体
# - name = foo（去掉下划线，首字母大写），type = "tube"
# - OD / ID 两条 dimension，从 find_drg() 补充 Cpk
# - missing_dimensions 始终包含 ["length", "bend_profile", "clip_positions"]

components = []

geo_od_keys = [k for k in geometry if k.endswith('_od_mm') and not any(
    excl in k for excl in ['end_form', 'engine_hp_port', 'damper', 'port_connection']
)]

for od_key in geo_od_keys:
    base = od_key[:-len('_od_mm')]
    id_key = base + '_id_mm'
    if id_key not in geometry:
        continue
    comp_num = comp_counter[0] + 1
    comp_id = make_comp_id()
    name = base.replace('_', ' ').title()
    od_val = geometry[od_key]
    id_val = geometry[id_key]
    dims = []
    for param, val, src_suffix in [('OD', od_val, od_key), ('ID', id_val, id_key)]:
        nominal, t_plus, t_minus = parse_tolerance(val)
        drg_ind = find_drg(f"{name} {param}") or find_drg(param)
        dims.append({
            "id": make_dim_id(comp_num),
            "parameter": param,
            "nominal": nominal,
            "tolerance_plus": t_plus,
            "tolerance_minus": t_minus,
            "unit": "mm",
            "cpk_target": extract_cpk(drg_ind),
            "gdt_symbol": None,
            "source_drg": drg_ind['id'] if drg_ind else None,
            "source_n01": f"geometry.{src_suffix}",
            "confidence": "S1",
            "needs_review": drg_ind['needs_review'] if drg_ind else False,
        })
    components.append({
        "id": comp_id,
        "name": name,
        "type": "tube",
        "quantity": 1,
        "material_hint": "",   # 从 material_compliance 或 SC/CC 填充（Step 2f）
        "dimensions": dims,
        "missing_dimensions": ["length", "bend_profile", "clip_positions"],
    })
```

### 2c. 识别端成形（end_form）

```python
# 如果 geometry 包含 'end_form' 子节点，识别为独立组件
if 'end_form' in geometry:
    ef = geometry['end_form']
    comp_num = comp_counter[0] + 1
    comp_id = make_comp_id()
    dims = []
    for param, key in [('OD', 'od_mm'), ('ID', 'id_mm'), ('Length', 'length_mm')]:
        val = ef.get(key)
        if val is None:
            continue
        nominal, t_plus, t_minus = parse_tolerance(val)
        drg_kw = f"end-form {param.lower()}" if param != 'Length' else "end-form length"
        drg_ind = find_drg(drg_kw) or find_drg(f"end form {param.lower()}")
        dims.append({
            "id": make_dim_id(comp_num),
            "parameter": param,
            "nominal": nominal,
            "tolerance_plus": t_plus,
            "tolerance_minus": t_minus,
            "unit": "mm",
            "cpk_target": extract_cpk(drg_ind) or 1.33,
            "gdt_symbol": None,
            "source_drg": drg_ind['id'] if drg_ind else None,
            "source_n01": f"geometry.end_form.{key}",
            "confidence": ef.get('confidence', 'S1'),
            "needs_review": drg_ind['needs_review'] if drg_ind else False,
        })
    components.append({
        "id": comp_id,
        "name": "End-form",
        "type": "end_form",
        "quantity": 1,
        "material_hint": "Steel or aluminum (per drawing)",
        "dimensions": dims,
        "missing_dimensions": ["barb profile detail"] if ef.get('barbs') else ["barb count", "barb profile"],
    })
```

### 2d. 识别减振器（damper）

```python
# 如果 geometry 包含 'damper' 子节点
if 'damper' in geometry:
    d = geometry['damper']
    comp_num = comp_counter[0] + 1
    comp_id = make_comp_id()
    dims = []
    for param, key, drg_kw in [
        ('OD',       'outer_diameter_mm',      'damper od'),
        ('Width',    'width_mm_with_tolerance', 'damper width'),
        ('Port OD',  'port_connection_od_mm',   'damper port'),
    ]:
        val = d.get(key)
        if val is None:
            continue
        nominal, t_plus, t_minus = parse_tolerance(val)
        drg_ind = find_drg(drg_kw)
        dims.append({
            "id": make_dim_id(comp_num),
            "parameter": param,
            "nominal": nominal,
            "tolerance_plus": t_plus,
            "tolerance_minus": t_minus,
            "unit": "mm",
            "cpk_target": None,
            "gdt_symbol": None,
            "source_drg": drg_ind['id'] if drg_ind else None,
            "source_n01": f"geometry.damper.{key}",
            "confidence": "S2",
            "needs_review": True,
        })
    supplier = d.get('supplier', 'unknown supplier')
    components.append({
        "id": comp_id,
        "name": f"Damper ({supplier})",
        "type": "damper",
        "quantity": 1,
        "material_hint": "Supplier-provided assembly",
        "dimensions": dims,
        "missing_dimensions": ["internal geometry", "resonance frequency range"],
    })
```

### 2e. 识别快接头（quick_connector）

```python
# 如果 n01.quick_connector 存在，每个已填充的 side 创建一个 QC 组件
if qc:
    for side_name, field in [
        ("Filter side feed",   "fuel_filter_side_feed"),
        ("Filter side return", "fuel_filter_side_return"),
        ("Engine bay",         "engine_bay_side"),
    ]:
        val = qc.get(field)
        if not val:
            continue
        comp_id = make_comp_id()
        components.append({
            "id": comp_id,
            "name": f"Quick Connector ({side_name})",
            "type": "quick_connector",
            "quantity": 1,
            "material_hint": val if isinstance(val, str) else "",
            "dimensions": [],
            "missing_dimensions": ["housing OD/ID", "latch geometry", "retention force profile"],
        })
```

### 2f. 识别密封件（seal）

```python
# 从 n01.quick_connector.o_ring_materials 识别 O 型圈
o_rings = qc.get('o_ring_materials', {}) if qc else {}
for seal_label, mat_field in [
    ("O-ring (fuel contact)", "fuel_contact"),
    ("O-ring (external)",     "external"),
]:
    mat = o_rings.get(mat_field)
    if not mat:
        continue
    comp_id = make_comp_id()
    components.append({
        "id": comp_id,
        "name": seal_label,
        "type": "seal",
        "quantity": 2,
        "material_hint": mat,
        "dimensions": [],
        "missing_dimensions": ["cross-section OD", "groove dimensions"],
    })
```

---

## Step 3: 构建装配接口

```python
log.step("Step 3: Build assembly interfaces")

# 按类型建立组件 ID 索引
comp_by_type: dict[str, list[str]] = {}
for c in components:
    comp_by_type.setdefault(c['type'], []).append(c['id'])

interfaces = []
intf_counter = [0]

def make_intf_id() -> str:
    intf_counter[0] += 1
    return f"INTF-{intf_counter[0]:02d}"

# PSEUDOCODE — AI 执行时根据下列规则内联构建接口
#
# 规则 1: end_form 存在 → 管体与发动机 HP 口之间有 quick_connect 接口
#   - 关联组件: tube[] + quick_connector(engine bay)
#   - mating_dimensions: end_form.od_mm / id_mm / length_mm + engine_hp_port.outer_diameter_mm
#   - sc_cc_refs: sc_cc_refs_for("leak", "pull-off", "secondary latch")
#
# 规则 2: 存在 filter side QC 组件 → 管体与滤清器侧接口有 quick_connect 接口
#   - 关联组件: tube[] + filter_side_qc[]
#   - sc_cc_refs: sc_cc_refs_for("leak", "impurities", "cleanliness")
#
# 规则 3: damper 存在 → 管体与减振器有 press_fit 接口
#   - 关联组件: tube[0] + damper[0]
#   - mating_dimensions: geometry.damper.port_connection_od_mm
#   - sc_cc_refs: sc_cc_refs_for("static charge", "ESD", "conductive")
#   - needs_review: True（因为 damper 尺寸为 S2）
```

---

## Step 4: 完整度计算、Gap 识别、写 Artifact

```python
log.step("Step 4: Completeness + gaps + write artifact")

total_dims    = sum(len(c['dimensions']) for c in components)
total_missing = sum(len(c.get('missing_dimensions', [])) for c in components)
completeness_pct = round(total_dims / max(total_dims + total_missing, 1) * 100)

missing_from_3d = [
    "Assembly routing and bend angles",
    "Clip/bracket positions and spacing",
    "Package envelope validation",
]

# Gap 识别
gaps = []
if not components:
    gaps.append({
        "rule": "R-03-01",
        "msg": "n01.geometry empty — no components identified",
        "severity": "error", "assumption": None
    })
# R-03-02 始终触发（无 3D 模型）
gaps.append({
    "rule": "R-03-02",
    "msg": "3D model not available — geometry sourced from n01+n02 fallback",
    "severity": "warning", "assumption": None
})
# R-03-03: 有任意组件有缺失尺寸
if any(c.get('missing_dimensions') for c in components):
    names = [c['id'] for c in components if c.get('missing_dimensions')]
    gaps.append({
        "rule": "R-03-03",
        "msg": f"{len(names)} component(s) have missing dimensions: {names}",
        "severity": "warning", "assumption": None
    })
# R-03-04: SC/CC 尺寸指标存在但接口为空
sc_dim = [s for s in sc_cc if any(
    kw in s.get('parameter', '').lower() for kw in ['dimension', 'od', 'id', 'leak', 'pull']
)]
intf_sc_refs = [ref for intf in interfaces for ref in intf.get('sc_cc_refs', [])]
if sc_dim and not intf_sc_refs:
    gaps.append({
        "rule": "R-03-04",
        "msg": "SC/CC dimensional items found but no assembly interface SC/CC refs recorded",
        "severity": "warning", "assumption": None
    })

for g in gaps:
    log.gap(g['rule'], g['msg'], g['severity'])

# 置信度底线
all_confs = [d.get('confidence', 'S1') for c in components for d in c.get('dimensions', [])]
confidence_floor = max(all_confs, key=lambda s: int(s[1:])) if all_confs else 'S1'

artifact = {
    "node": "n03",
    "project": project_path.name,
    "status": "ready",
    "produced_at": datetime.now(timezone.utc).isoformat(),
    "confidence_floor": confidence_floor,
    "gaps": gaps,
    "assumptions": [],
    "payload": {
        "geometry_version": 1,
        "has_3d_model": False,
        "completeness_pct": completeness_pct,
        "missing_from_3d": missing_from_3d,
        "components": components,
        "assembly_interfaces": interfaces,
    }
}

store.write('n03', artifact)
log.done(artifact)

execution_summary = f"""n03 executed in **fallback mode** (no 3D model).

- 数据来源: n01.geometry + n01.quick_connector + n02 CAT-04
- 识别组件: {len(components)} 个
- 装配接口: {len(interfaces)} 个
- 几何完整度: {completeness_pct}%
- 置信度底线: {confidence_floor}
- 缺失（等待 3D 模型）: {missing_from_3d}
"""
report = NodeReport(str(project_path), 'n03')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
```

---

## Validation

```python
import sys, json
from pathlib import Path

project_path = Path('<project_path>')
sys.path.insert(0, str(Path('<apqp_os_root>/.claude/skills/apqp-os/scripts')))
from store import ArtifactStore

store = ArtifactStore(str(project_path))
a = store.read('n03')
p = a['payload']

assert a['status'] == 'ready'
assert isinstance(p.get('components'), list) and len(p['components']) > 0, "no components"
assert isinstance(p.get('assembly_interfaces'), list), "interfaces missing"
assert 0 < p.get('completeness_pct', 0) <= 100, "completeness_pct out of range"
assert p.get('has_3d_model') is False or p.get('has_3d_model') is True

# 每个组件必须有必填字段
for c in p['components']:
    for key in ['id', 'name', 'type', 'quantity', 'dimensions', 'missing_dimensions']:
        assert key in c, f"{c.get('id')} missing {key}"
    for d in c.get('dimensions', []):
        for key in ['id', 'parameter', 'nominal', 'unit', 'confidence', 'needs_review']:
            assert key in d, f"dim {d.get('id')} missing {key}"

# R-03-02 始终在 gaps 中
gap_rules = [g['rule'] for g in a.get('gaps', [])]
assert 'R-03-02' in gap_rules, "R-03-02 missing"

tube_comps = [c for c in p['components'] if c['type'] == 'tube']
assert len(tube_comps) > 0, "no tube components identified"

print(f"✓ n03 valid")
print(f"  组件: {len(p['components'])} | 接口: {len(p['assembly_interfaces'])}")
print(f"  完整度: {p['completeness_pct']}% | has_3d_model: {p['has_3d_model']}")
print(f"  置信度底线: {a['confidence_floor']}")
print(f"  Gaps: {gap_rules}")
```
````

### Step 2: 运行完整度验证

```bash
python3 -c "
from pathlib import Path
f = Path('/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/references/n03-requirements.md')
assert f.exists()
text = f.read_text()
required = ['Precondition', 'Step 1', 'Step 2', 'Step 3', 'Step 4', 'Validation',
            'make_comp_id', 'make_dim_id', 'find_drg', 'parse_tolerance',
            'assembly_interfaces', 'completeness_pct', 'has_3d_model',
            'R-03-01', 'R-03-02', 'R-03-03', 'R-03-04',
            'ArtifactStore', 'NodeLogger', 'NodeReport']
for s in required:
    assert s in text, f'Missing: {s}'
print(f'✓ n03-requirements.md complete ({len(text.splitlines())} lines)')
"
```

预期: `✓ n03-requirements.md complete (...lines)`

### Step 3: Commit

```bash
cd /home/chu2026/Documents/APQPOS
git add .claude/skills/apqp-os/references/n03-requirements.md
git commit -m "feat: add n03-requirements.md — 3D 数模解析执行指南"
```

---

## Task 3: 在 FBFS 项目执行 n03 并验证

**Files:**
- Read: `FBFS/artifacts/n01-output.json`, `FBFS/artifacts/n02-output.json`
- Create: `FBFS/artifacts/n03-output.json`, `FBFS/reports/n03-report-*.md`, `FBFS/logs/n03-*.md`

### Step 1: 确认 n01 / n02 状态

```bash
python3 -c "
import sys, json
from pathlib import Path
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore
store = ArtifactStore('/home/chu2026/Documents/APQPOS/FBFS')
n01 = store.read('n01')
n02 = store.read('n02')
assert n01['status'] == 'ready', 'n01 not ready'
assert n02['status'] == 'ready', 'n02 not ready'
geo = n01['payload'].get('geometry', {})
print(f'n01 geometry keys: {list(geo.keys())}')
print(f'n02 CAT-04 indicators: ready')
print('✓ Precondition OK')
"
```

预期: 输出 geometry 键列表，包含 `feed_line_od_mm`, `return_line_od_mm`, `end_form`, `damper` 等

### Step 2: 按 n03-requirements.md 执行节点

按指南逐步执行：
1. 读取 n01 geometry + quick_connector + material_compliance + sc_cc
2. 读取 n02 CAT-04 indicators
3. Step 2b: 识别管体（feed tube / return tube）
4. Step 2c: 识别 end_form
5. Step 2d: 识别 damper
6. Step 2e: 识别 quick_connector（3 个 side）
7. Step 2f: 识别 O-ring（fuel contact / external）
8. Step 3: 构建 3 个装配接口（tube→HP port, tube→filter, tube→damper）
9. Step 4: 计算完整度，生成 gaps，写 artifact

**预期组件数: ≥ 7**（2 管体 + 1 end_form + 1 damper + 3 QC + 2 O-ring = 9）
**预期接口数: 3**

### Step 3: 运行 Validation

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('/home/chu2026/Documents/APQPOS/FBFS')
a = store.read('n03')
p = a['payload']

assert a['status'] == 'ready'
assert len(p['components']) >= 7, f'Expected ≥7 components, got {len(p[\"components\"])}'
assert len(p['assembly_interfaces']) >= 2, 'Expected ≥2 interfaces'
assert 0 < p['completeness_pct'] <= 100
assert 'R-03-02' in [g['rule'] for g in a.get('gaps', [])]

tube_comps = [c for c in p['components'] if c['type'] == 'tube']
assert len(tube_comps) >= 1, 'No tube components found'

for c in p['components']:
    for key in ['id', 'name', 'type', 'quantity', 'dimensions', 'missing_dimensions']:
        assert key in c, f'{c.get(\"id\")} missing {key}'
    for d in c.get('dimensions', []):
        for key in ['id', 'parameter', 'nominal', 'unit', 'confidence', 'needs_review']:
            assert key in d, f'dim {d.get(\"id\")} missing {key}'

print(f'✓ n03 valid')
print(f'  组件: {len(p[\"components\"])} | 接口: {len(p[\"assembly_interfaces\"])}')
print(f'  完整度: {p[\"completeness_pct\"]}% | has_3d_model: {p[\"has_3d_model\"]}')
print(f'  置信度底线: {a[\"confidence_floor\"]}')
print(f'  Gaps: {[g[\"rule\"] for g in a.get(\"gaps\", [])]}')
"
```

### Step 4: Commit

```bash
cd /home/chu2026/Documents/APQPOS
git add FBFS/artifacts/n03-output.json FBFS/reports/ FBFS/logs/
git commit -m "feat: run n03 on FBFS — component tree and assembly interfaces generated"
```
