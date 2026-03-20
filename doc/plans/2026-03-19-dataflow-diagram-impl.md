# Dataflow Diagram Generator — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `scripts/diagram.py` that reads all project artifacts and generates a single-file HTML dataflow diagram, updated progressively after each node execution.

**Architecture:** A single Python class `DataflowDiagram` builds HTML via string concatenation. It reads all `nXX-output.json` from the project's `artifacts/` dir, maps each node to a fixed SVG position, and outputs `artifacts/dataflow-diagram.html`. Nodes with artifacts are rendered in color with data; pending nodes are grey placeholders.

**Tech Stack:** Pure Python 3 (no external deps), SVG for flow diagram, vanilla JS for drawer interaction.

---

### Task 1: Create diagram.py scaffold with data loading

**Files:**
- Create: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Create the scaffold**

```python
#!/usr/bin/env python3
"""APQP dataflow diagram generator — produces a single-file HTML visualization.

Reads all nXX-output.json artifacts from a project directory and generates
an interactive SVG-based dataflow diagram at artifacts/dataflow-diagram.html.

Usage:
    from diagram import DataflowDiagram
    DataflowDiagram('/path/to/project').generate()
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from store import ArtifactStore

NETWORK_JSON = Path(__file__).parent.parent / "references" / "network.json"

NODE_NAMES = {
    "n01": "RFQ 提取",       "n02": "DRG 指标",
    "n03": "组件树",          "n04": "BOM 清单",
    "n05": "材料选型",        "n06": "用量计算",
    "n07": "DFMEA",           "n08": "工艺路线",
    "n09": "DVP&R",           "n10": "PFD",
    "n11": "材料成本",        "n12": "转化成本",
    "n13": "产能规划",        "n14": "项目计划",
    "n15": "EDD",             "n16": "RC 成本",
    "n17": "NRC 总投入",      "n18": "报价",
}

# Phase assignment for color coding
NODE_PHASE = {
    "n01": 1, "n02": 1, "n03": 1,
    "n04": 2, "n05": 2, "n06": 2, "n07": 2, "n08": 2,
    "n09": 3, "n10": 3,
    "n11": 4, "n12": 4, "n13": 4,
    "n14": 5, "n15": 5,
    "n16": 6, "n17": 6, "n18": 6,
}

PHASE_COLORS = {
    1: {"stroke": "#3b82f6", "fill_grad": "grad-phase1", "text": "#3b82f6"},   # blue - requirements
    2: {"stroke": "#06b6d4", "fill_grad": "grad-phase2", "text": "#06b6d4"},   # cyan - decomposition
    3: {"stroke": "#8b5cf6", "fill_grad": "grad-phase3", "text": "#8b5cf6"},   # purple - validation
    4: {"stroke": "#10b981", "fill_grad": "grad-phase4", "text": "#10b981"},   # emerald - cost
    5: {"stroke": "#ec4899", "fill_grad": "grad-phase5", "text": "#ec4899"},   # pink - planning
    6: {"stroke": "#f59e0b", "fill_grad": "grad-phase6", "text": "#f59e0b"},   # amber - quotation
}

PENDING_STYLE = {"stroke": "#2a3040", "fill": "#1a1f2e", "text": "#4a5568"}

# Fixed layout: {node_id: (x, y, width, height)}
# Full 18-node DAG layout optimized for readability
NODE_LAYOUT = {
    # Row 1: Requirements chain
    "n01": (60,  40,  180, 80),
    "n02": (300, 40,  180, 80),
    "n03": (540, 40,  180, 80),
    # Row 2: Decomposition (n03 fan-out)
    "n04": (60,  200, 180, 80),
    "n05": (300, 200, 180, 80),
    "n06": (540, 200, 180, 80),
    "n07": (780, 200, 180, 80),
    "n08": (1020,200, 200, 80),
    # Row 3: Validation & PFD
    "n09": (780, 360, 180, 80),
    "n10": (540, 360, 180, 80),
    # Row 4: Cost calculation
    "n11": (60,  360, 160, 80),
    "n12": (280, 360, 160, 80),
    "n13": (1020,360, 180, 80),
    # Row 5: Planning & NRC
    "n14": (1020,520, 180, 80),
    "n15": (780, 520, 180, 80),
    # Row 6: Final quotation
    "n16": (60,  520, 160, 100),
    "n17": (540, 520, 160, 80),
    "n18": (300, 680, 180, 100),
}

# Edge paths: (from_node, to_node, svg_path_d, color_key, particle_dur, particle_begin)
# These are pre-computed SVG path strings connecting the fixed node positions
# Will be populated in Task 2


class DataflowDiagram:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.store = ArtifactStore(project_path)
        self.network = json.loads(NETWORK_JSON.read_text())
        self.artifacts: dict[str, dict | None] = {}
        self._load_artifacts()

    def _load_artifacts(self):
        for node in self.network["nodes"]:
            nid = node["id"]
            self.artifacts[nid] = self.store.read(nid)

    def _is_ready(self, node_id: str) -> bool:
        a = self.artifacts.get(node_id)
        return a is not None and a.get("status") in ("ready", "done", "waiting_human")

    def _get_project_info(self) -> dict:
        proj_file = self.project_path / "project.json"
        if proj_file.exists():
            return json.loads(proj_file.read_text())
        return {}

    def generate(self) -> Path:
        """Generate the dataflow diagram HTML and return its path."""
        proj = self._get_project_info()
        html = self._render_full_html(proj)
        out = self.project_path / "artifacts" / "dataflow-diagram.html"
        out.write_text(html, encoding="utf-8")
        print(f"[DIAGRAM] {out.name} updated")
        return out

    def _render_full_html(self, proj: dict) -> str:
        # Will be built out in subsequent tasks
        parts = [
            self._render_html_head(proj),
            '<body>\n<div class="page-wrapper">',
            self._render_header(proj),
            self._render_flow_svg(),
            self._render_cost_bar(),
            self._render_reliability(),
            self._render_legend(),
            self._render_footer(proj),
            '</div>',
            self._render_drawer_html(),
            self._render_script(),
            '</body>\n</html>',
        ]
        return "\n".join(parts)

    def _render_html_head(self, proj: dict) -> str:
        title = f"Q^AI 成本数据流图 · {proj.get('customer', '')} {proj.get('id', '')}"
        return f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n<title>{title}</title>\n</head>'

    def _render_header(self, proj: dict) -> str:
        return '<!-- header placeholder -->'

    def _render_flow_svg(self) -> str:
        return '<!-- svg placeholder -->'

    def _render_cost_bar(self) -> str:
        return '<!-- cost bar placeholder -->'

    def _render_reliability(self) -> str:
        return '<!-- reliability placeholder -->'

    def _render_legend(self) -> str:
        return '<!-- legend placeholder -->'

    def _render_footer(self, proj: dict) -> str:
        return '<!-- footer placeholder -->'

    def _render_drawer_html(self) -> str:
        return '<!-- drawer placeholder -->'

    def _render_script(self) -> str:
        return '<script>/* placeholder */</script>'
```

**Step 2: Verify it loads and runs**

Run: `cd /home/chu2026/Documents/APQPOS && python3 -c "import sys; sys.path.insert(0,'.claude/skills/apqp-os/scripts'); from diagram import DataflowDiagram; d = DataflowDiagram('FBFS'); p = d.generate(); print('OK:', p)"`
Expected: Creates `FBFS/artifacts/dataflow-diagram.html` with placeholder content.

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat: add diagram.py scaffold — DataflowDiagram class with data loading"
```

---

### Task 2: Implement CSS styles

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Replace `_render_html_head` with full CSS**

Port all CSS from `FBFS/artifacts/dataflow-diagram.html` lines 7-566, plus add:
- `.drawer` — right-side panel: `position: fixed; right: -420px; top: 0; width: 420px; height: 100vh; transition: right 0.3s; z-index: 50; overflow-y: auto; background: var(--bg-card); border-left: 1px solid var(--border);`
- `.drawer.open` — `right: 0;`
- `.drawer-header`, `.drawer-section`, `.drawer-kv-table` — detail panel styling
- `.node-pending .node-rect` — `stroke-dasharray: 6,4; opacity: 0.5`
- `.cost-segment` hover fix — use `transform: scaleY(1.08); filter: brightness(1.2)` instead of `flex-grow`
- `.cost-segment:active` — click highlight

The `_render_html_head` method returns a string with `<!DOCTYPE html>` through `</style>\n</head>`.

**Step 2: Verify the file still loads**

Run: `cd /home/chu2026/Documents/APQPOS && python3 -c "import sys; sys.path.insert(0,'.claude/skills/apqp-os/scripts'); from diagram import DataflowDiagram; d = DataflowDiagram('FBFS'); d.generate(); print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): add full CSS styles including drawer and pending states"
```

---

### Task 3: Implement header rendering

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Implement `_render_header`**

Extract from artifacts:
- RC unit price from n16: `artifacts['n16']['payload']['total_rc_eur']` (or "—" if pending)
- NRC total from n17: `artifacts['n17']['payload']['total_nrc_eur']` (or "—" if pending)
- Part name/number from n01: `artifacts['n01']['payload']['part_name']`
- Customer from project.json
- Progress: count of ready nodes / 18

```python
def _render_header(self, proj: dict) -> str:
    n01 = self.artifacts.get("n01")
    n16 = self.artifacts.get("n16")
    n17 = self.artifacts.get("n17")

    part_name = ""
    if n01 and self._is_ready("n01"):
        p = n01.get("payload", {})
        part_name = f"{p.get('part_number', '')} {p.get('part_name', '')}"

    rc_val = "—"
    if n16 and self._is_ready("n16"):
        rc = n16["payload"].get("total_rc_eur")
        if rc is not None:
            rc_val = f"€{rc:.2f}"

    nrc_val = "—"
    if n17 and self._is_ready("n17"):
        nrc = n17["payload"].get("total_nrc_eur")
        if nrc is not None:
            nrc_val = f"€{nrc/10000:.1f}万"

    done_count = sum(1 for nid in NODE_NAMES if self._is_ready(nid))
    customer = proj.get("customer", "")
    subtitle = f"从 RFQ 提取到最终报价，完整追踪 18 节点数据链路"

    return f'''
    <header class="header animate-in">
      <div class="header-left">
        <div class="header-badge">Q^AI Data Flow</div>
        <h1>{customer} · {part_name}</h1>
        <p class="header-subtitle">{subtitle}<br>进度 {done_count}/18 节点</p>
      </div>
      <div class="header-stats">
        <div class="stat-block">
          <div class="stat-value">{rc_val}</div>
          <div class="stat-label">RC 单件成本</div>
        </div>
        <div class="stat-block">
          <div class="stat-value">{nrc_val}</div>
          <div class="stat-label">NRC 工程费用</div>
        </div>
      </div>
    </header>'''
```

**Step 2: Generate and verify header appears**

Run: `cd /home/chu2026/Documents/APQPOS && python3 -c "import sys; sys.path.insert(0,'.claude/skills/apqp-os/scripts'); from diagram import DataflowDiagram; d = DataflowDiagram('FBFS'); d.generate()"`
Then open `FBFS/artifacts/dataflow-diagram.html` in browser — verify header shows "Stellantis · FC00SAA78530 Fuel supply line", RC=€41.87, NRC=€167.9万.

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): implement header with RC/NRC stats from artifacts"
```

---

### Task 4: Implement node SVG rendering (the core)

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Add node summary extraction**

Add a method `_node_summary(node_id)` that returns a dict `{line1, line2, value}` for the SVG text lines:

```python
def _node_summary(self, node_id: str) -> dict:
    """Extract 2-3 summary lines for SVG display from artifact payload."""
    a = self.artifacts.get(node_id)
    if not a or not self._is_ready(node_id):
        return {"line1": "—", "line2": "", "value": ""}

    p = a.get("payload", {})
    conf = a.get("confidence_floor", "?")

    # Node-specific extraction
    if node_id == "n01":
        reqs = p.get("performance_requirements", [])
        files = p.get("source_index", {})
        geo = p.get("geometry", {})
        od = geo.get("feed_line_od_mm", "?")
        id_ = geo.get("feed_line_id_mm", "?")
        pbar = p.get("working_pressure_bar", "?")
        return {"line1": f"{len(files)} 份文件 → {len(reqs)} 项需求",
                "line2": "", "value": f"管径 {od}×{id_}mm · {pbar}bar"}

    elif node_id == "n02":
        cats = p.get("categories", [])
        total = sum(len(c.get("indicators", [])) for c in cats)
        review = p.get("review_required_count", 0)
        return {"line1": f"{total} 条 DRG 指标",
                "line2": f"待审阅 {review} 条", "value": ""}

    elif node_id == "n03":
        comps = p.get("components", [])
        pct = p.get("completeness_pct", 0)
        has_3d = "✓3D" if p.get("has_3d_model") else "无3D"
        return {"line1": f"{len(comps)} 个组件 · {has_3d}",
                "line2": f"完整度 {pct}%", "value": ""}

    elif node_id == "n04":
        items = p.get("bom_items", p.get("items", []))
        make = sum(1 for i in items if i.get("make_or_buy") == "make")
        buy = len(items) - make
        return {"line1": f"{len(items)} 个组件",
                "line2": f"{make} make · {buy} buy", "value": ""}

    elif node_id == "n05":
        materials = p.get("materials", p.get("component_materials", []))
        return {"line1": f"{len(materials)} 项材料选型",
                "line2": "", "value": f"[{conf}]"}

    elif node_id == "n06":
        summary = p.get("weight_summary", p.get("summary", {}))
        gross = summary.get("total_gross_weight_g", p.get("total_gross_weight_g", "?"))
        return {"line1": f"毛重 {gross}g",
                "line2": "", "value": "材料消耗量"}

    elif node_id == "n07":
        items = p.get("fmea_items", p.get("failure_modes", []))
        high_rpn = sum(1 for i in items if (i.get("rpn", 0) or 0) >= 100)
        return {"line1": f"{len(items)} 个失效模式",
                "line2": f"高 RPN ≥100: {high_rpn}", "value": ""}

    elif node_id == "n08":
        ops = p.get("operations", p.get("process_steps", []))
        inv = p.get("total_investment_eur", 0)
        inv_str = f"€{inv/10000:.0f}万" if inv >= 10000 else f"€{inv:.0f}"
        return {"line1": f"{len(ops)} 道工序",
                "line2": f"投资 {inv_str}", "value": ""}

    elif node_id == "n09":
        tests = p.get("test_items", p.get("dvpr_items", []))
        return {"line1": f"{len(tests)} 个验证项",
                "line2": "", "value": "DVP&R"}

    elif node_id == "n10":
        steps = p.get("pfd_steps", p.get("process_flow", []))
        return {"line1": f"{len(steps)} 道工序流程",
                "line2": "", "value": "PFD + 控制计划"}

    elif node_id == "n11":
        total = p.get("total_material_cost_eur", p.get("total", 0))
        make_t = p.get("make_total_eur", p.get("make_total", 0))
        buy_t = p.get("buy_total_eur", p.get("buy_total", 0))
        return {"line1": "", "line2": f"make €{make_t:.2f} + buy €{buy_t:.2f}",
                "value": f"€{total:.2f} /件"}

    elif node_id == "n12":
        total = p.get("total_conversion_cost_eur", 0)
        return {"line1": "", "line2": "人工+设备+管理费",
                "value": f"€{total:.2f} /件"}

    elif node_id == "n13":
        line_cap = p.get("line_capacity_per_year", p.get("annual_capacity", "?"))
        util = p.get("utilization_pct", "?")
        return {"line1": f"产能 {line_cap}/yr",
                "line2": f"利用率 {util}%", "value": ""}

    elif node_id == "n14":
        milestones = p.get("milestones", [])
        return {"line1": f"{len(milestones)} 个里程碑",
                "line2": "", "value": "项目计划"}

    elif node_id == "n15":
        total = p.get("edd_total_eur", 0)
        total_str = f"€{total/10000:.1f}万" if total >= 10000 else f"€{total:.0f}"
        return {"line1": "", "line2": "工程开发费",
                "value": total_str}

    elif node_id == "n16":
        total = p.get("total_rc_eur", 0)
        bd = p.get("cost_breakdown_pct", {})
        mat_pct = bd.get("material", 0)
        conv_pct = bd.get("conversion", 0)
        return {"line1": f"材料{mat_pct:.0f}%",
                "line2": f"加工{conv_pct:.0f}%",
                "value": f"€{total:.2f}"}

    elif node_id == "n17":
        total_nrc = p.get("total_nrc_eur", 0)
        amort = p.get("amortization_plan", {})
        per_piece = amort.get("nrc_per_piece_eur", 0)
        total_str = f"€{total_nrc/10000:.1f}万" if total_nrc >= 10000 else f"€{total_nrc:.0f}"
        return {"line1": f"一次性 {total_str}",
                "line2": "",
                "value": f"€{per_piece:.2f} /件"}

    elif node_id == "n18":
        qs = p.get("quotation_summary", {})
        unit = qs.get("unit_price_eur", 0)
        nrc = qs.get("nrc_total_eur", 0)
        rev = qs.get("annual_revenue_eur", 0)
        nrc_str = f"€{nrc/10000:.1f}万" if nrc >= 10000 else f"€{nrc:.0f}"
        rev_str = f"€{rev/10000:.0f}万" if rev >= 10000 else f"€{rev:.0f}"
        return {"line1": f"+ NRC {nrc_str}",
                "line2": f"年收入 {rev_str}",
                "value": f"€{unit:.2f}"}

    return {"line1": f"[{conf}]", "line2": "", "value": ""}
```

**Step 2: Implement `_render_single_node` and `_render_flow_svg`**

```python
def _render_single_node(self, node_id: str) -> str:
    x, y, w, h = NODE_LAYOUT[node_id]
    tx = x + 20  # text x offset
    ready = self._is_ready(node_id)
    phase = NODE_PHASE[node_id]
    pc = PHASE_COLORS[phase]
    name = NODE_NAMES[node_id]

    if ready:
        fill = f"url(#{pc['fill_grad']})"
        stroke = pc["stroke"]
        stroke_dash = ""
        id_color = pc["text"]
        title_color = "#e2e8f0"
        detail_color = "#94a3b8"
        value_color = pc["text"]
        summary = self._node_summary(node_id)
    else:
        fill = PENDING_STYLE["fill"]
        stroke = PENDING_STYLE["stroke"]
        stroke_dash = ' stroke-dasharray="6,4"'
        id_color = PENDING_STYLE["text"]
        title_color = PENDING_STYLE["text"]
        detail_color = PENDING_STYLE["text"]
        value_color = PENDING_STYLE["text"]
        summary = {"line1": "—", "line2": "", "value": ""}

    lines = [f'<g class="node-group" data-node="{node_id}">']
    lines.append(f'  <rect class="node-rect" x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}"{stroke_dash}/>')

    # Glow rect for key cost nodes
    if ready and node_id in ("n16", "n17", "n18"):
        lines.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10" fill="none" stroke="{stroke}" stroke-width="2" opacity="0.3">')
        lines.append(f'    <animate attributeName="opacity" values="0.3;0.6;0.3" dur="3s" repeatCount="indefinite"/>')
        lines.append(f'  </rect>')

    # Text lines
    lines.append(f'  <text class="node-id" x="{tx}" y="{y+21}" fill="{id_color}">{node_id.upper()}</text>')
    lines.append(f'  <text class="node-title" x="{tx}" y="{y+39}" fill="{title_color}">{name}</text>')

    if summary.get("value"):
        # Value is prominent — put it before detail lines
        font_size = "18px" if node_id == "n18" else "14px" if node_id in ("n11","n12","n15","n16","n17") else "11px"
        lines.append(f'  <text class="node-value" x="{tx}" y="{y+57}" fill="{value_color}" style="font-size:{font_size};font-weight:700">{summary["value"]}</text>')
        if summary.get("line1"):
            lines.append(f'  <text class="node-detail" x="{tx}" y="{y+71}" fill="{detail_color}">{summary["line1"]}</text>')
        if summary.get("line2"):
            lines.append(f'  <text class="node-detail" x="{tx}" y="{y+84}" fill="{detail_color}">{summary["line2"]}</text>')
    else:
        if summary.get("line1"):
            lines.append(f'  <text class="node-detail" x="{tx}" y="{y+57}" fill="{detail_color}">{summary["line1"]}</text>')
        if summary.get("line2"):
            lines.append(f'  <text class="node-detail" x="{tx}" y="{y+71}" fill="{detail_color}">{summary["line2"]}</text>')

    lines.append('</g>')
    return "\n".join(lines)
```

**Step 3: Implement edge rendering with `_render_edges`**

Compute edge paths dynamically based on `NODE_LAYOUT` positions. For each edge in `network.json`, calculate SVG path from source node's output port to target node's input port. Use the edge's phase color. Only render particles if both endpoints are ready.

This method needs to:
1. Read `self.network["edges"]` (skip feedback edges)
2. For each edge, compute a path from source bottom/right to target top/left
3. Color based on source node's phase
4. Add animated particle circle only if both nodes are ready

```python
def _compute_edge_path(self, from_id: str, to_id: str) -> str:
    """Compute SVG path d attribute for an edge between two nodes."""
    fx, fy, fw, fh = NODE_LAYOUT[from_id]
    tx, ty, tw, th = NODE_LAYOUT[to_id]

    # Source: bottom center or right center
    # Target: top center or left center
    sx = fx + fw // 2
    sy = fy + fh
    ex = tx + tw // 2
    ey = ty

    # Simple routing: go down from source, then horizontal, then down to target
    mid_y = (sy + ey) // 2
    return f"M {sx} {sy} C {sx} {mid_y}, {ex} {mid_y}, {ex} {ey}"

def _render_edges(self) -> str:
    lines = []
    for edge in self.network["edges"]:
        if edge["type"] == "feedback":
            continue
        fid = edge["from"]
        tid = edge["to"]
        if fid not in NODE_LAYOUT or tid not in NODE_LAYOUT:
            continue

        both_ready = self._is_ready(fid) and self._is_ready(tid)
        phase = NODE_PHASE[fid]
        color = PHASE_COLORS[phase]["stroke"]
        path_d = self._compute_edge_path(fid, tid)

        if both_ready:
            lines.append(f'<path class="flow-path" d="{path_d}" stroke="{color}" marker-end="url(#arrow-{phase})"/>')
            # Animated particle
            dur = "3s"
            lines.append(f'<circle class="flow-particle" fill="{color}" filter="url(#glow)">')
            lines.append(f'  <animateMotion dur="{dur}" repeatCount="indefinite" path="{path_d}"/>')
            lines.append(f'</circle>')
        else:
            lines.append(f'<path class="flow-path" d="{path_d}" stroke="#2a3040" stroke-dasharray="4,6" opacity="0.4"/>')

    return "\n".join(lines)
```

**Step 4: Assemble `_render_flow_svg`**

```python
def _render_flow_svg(self) -> str:
    svg_lines = ['<div class="flow-container animate-in">']
    svg_lines.append('<svg class="flow-svg" viewBox="0 0 1300 850" xmlns="http://www.w3.org/2000/svg">')

    # Defs: gradients, markers, glow filter
    svg_lines.append(self._render_svg_defs())

    # Phase separator lines
    svg_lines.append(self._render_phase_separators())

    # Edges (behind nodes)
    svg_lines.append(self._render_edges())

    # Nodes
    for nid in NODE_LAYOUT:
        svg_lines.append(self._render_single_node(nid))

    # Phase labels
    svg_lines.append(self._render_phase_labels())

    svg_lines.append('</svg>')
    svg_lines.append('</div>')
    return "\n".join(svg_lines)
```

Helper methods `_render_svg_defs`, `_render_phase_separators`, `_render_phase_labels` generate the SVG defs block (gradients per phase, arrow markers per phase, glow filter), dashed separator lines between rows, and phase label text elements.

**Step 5: Generate and open in browser**

Run: `cd /home/chu2026/Documents/APQPOS && python3 -c "import sys; sys.path.insert(0,'.claude/skills/apqp-os/scripts'); from diagram import DataflowDiagram; DataflowDiagram('FBFS').generate()"`
Open `FBFS/artifacts/dataflow-diagram.html` — verify all 18 nodes visible, completed nodes in color with data, edges connecting them.

**Step 6: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): implement SVG node and edge rendering with 18-node layout"
```

---

### Task 5: Implement cost breakdown bar

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Implement `_render_cost_bar`**

Read n16 artifact's `cost_breakdown_pct` and absolute values. If n16 not ready, show grey placeholder bar.

```python
def _render_cost_bar(self) -> str:
    n16 = self.artifacts.get("n16")
    if not n16 or not self._is_ready("n16"):
        return '''
        <div class="cost-bar-section animate-in" style="opacity:0.3">
          <div class="cost-bar-title">单件成本结构 · 待计算</div>
          <div class="cost-bar-subtitle">RC 节点 (n16) 完成后显示</div>
          <div class="cost-bar-wrapper">
            <div class="cost-segment" style="flex:100; background:#2a3040;">—</div>
          </div>
        </div>'''

    p = n16["payload"]
    total = p.get("total_rc_eur", 0)
    bd = p.get("cost_breakdown_pct", {})

    segments = [
        ("材料", bd.get("material", 0), p.get("material_cost_eur", 0), "#0d9488"),
        ("加工", bd.get("conversion", 0), p.get("conversion_cost_eur", 0), "#3b82f6"),
        ("物流", bd.get("logistics", 0), p.get("logistics_eur", 0), "#8b5cf6"),
        ("质量", bd.get("quality", 0), p.get("quality_cost_eur", 0), "#ec4899"),
        ("管理", bd.get("overhead", 0), p.get("overhead_eur", 0), "#f59e0b"),
        ("利润", bd.get("profit", 0), p.get("profit_eur", 0), "#ef4444"),
    ]

    bar_html = []
    for label, pct, val, color in segments:
        display = f"{label} {pct:.0f}%" if pct >= 4 else ""
        bar_html.append(
            f'<div class="cost-segment" style="flex:{pct:.1f};background:{color}" '
            f'title="{label} €{val:.2f}" data-label="{label}" data-value="{val:.2f}" data-pct="{pct:.1f}">'
            f'<span>{display}</span></div>'
        )

    legend_html = []
    for label, pct, val, color in segments:
        legend_html.append(
            f'<div class="cost-legend-item">'
            f'<div class="cost-legend-swatch" style="background:{color}"></div>'
            f'<span>{label}</span>'
            f'<span class="cost-legend-value">€{val:.2f}</span></div>'
        )

    return f'''
    <div class="cost-bar-section animate-in">
      <div class="cost-bar-title">单件成本结构 · €{total:.2f}</div>
      <div class="cost-bar-subtitle">RC (Recurring Cost) 分项构成</div>
      <div class="cost-bar-wrapper">{"".join(bar_html)}</div>
      <div class="cost-legend">{"".join(legend_html)}</div>
    </div>'''
```

**Step 2: Generate and verify**

Run diagram generator, open HTML, verify cost bar shows 6 colored segments with correct percentages.

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): implement cost breakdown bar from n16 data"
```

---

### Task 6: Implement reliability risk matrix

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Implement `_render_reliability`**

Scan all artifacts for assumptions with confidence S3 or S4. Sort by estimated cost impact (heuristic: assumptions in cost nodes n11/n12/n15/n16/n17 ranked higher). Display as cards.

```python
def _render_reliability(self) -> str:
    risk_items = []
    for nid in NODE_NAMES:
        a = self.artifacts.get(nid)
        if not a or not self._is_ready(nid):
            continue
        for assumption in a.get("assumptions", []):
            conf = assumption.get("confidence", "")
            if conf not in ("S3", "S4"):
                continue
            risk_items.append({
                "node": nid,
                "field": assumption.get("field", ""),
                "value": f'{assumption.get("value", "")} {assumption.get("unit", "")}'.strip(),
                "rationale": assumption.get("rationale", ""),
                "confidence": conf,
            })

    if not risk_items:
        return ''

    # Sort: S4 before S3, cost nodes first
    cost_nodes = {"n11", "n12", "n15", "n16", "n17", "n18"}
    risk_items.sort(key=lambda r: (0 if r["confidence"]=="S4" else 1, 0 if r["node"] in cost_nodes else 1))

    cards = []
    for r in risk_items[:8]:  # Top 8
        badge_class = "s4" if r["confidence"] == "S4" else "s3"
        badge_text = f'{r["confidence"]} {"推测" if r["confidence"]=="S4" else "经验"}'
        cards.append(f'''
        <div class="reliability-card {badge_class}">
          <div class="rel-info">
            <div class="rel-name">{r["field"]}</div>
            <div class="rel-impact">{r["node"].upper()} · {r["rationale"][:60]}</div>
          </div>
          <div class="rel-value">{r["value"]}</div>
          <div class="rel-badge {badge_class}">{badge_text}</div>
        </div>''')

    return f'''
    <div class="reliability-section animate-in">
      <div class="reliability-title">数据可靠性风险矩阵</div>
      <div class="reliability-grid">{"".join(cards)}</div>
    </div>'''
```

**Step 2: Generate and verify**

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): implement reliability risk matrix from S3/S4 assumptions"
```

---

### Task 7: Implement side drawer (click interaction)

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Implement `_render_drawer_html`**

Static HTML structure for the drawer panel:

```python
def _render_drawer_html(self) -> str:
    return '''
    <div class="drawer" id="drawer">
      <div class="drawer-header">
        <div>
          <span class="drawer-node-id" id="drawer-node-id"></span>
          <span class="drawer-node-title" id="drawer-node-title"></span>
        </div>
        <button class="drawer-close" id="drawer-close">&times;</button>
      </div>
      <div class="drawer-status" id="drawer-status"></div>
      <div class="drawer-body" id="drawer-body"></div>
    </div>
    <div class="drawer-overlay" id="drawer-overlay"></div>'''
```

**Step 2: Implement `_render_script`**

Build a JS object `nodeDetails` from all artifacts, then add click handlers:

```python
def _render_script(self) -> str:
    # Build node details data for JS
    details = {}
    for nid in NODE_NAMES:
        a = self.artifacts.get(nid)
        if not a or not self._is_ready(nid):
            details[nid] = {"status": "pending", "payload": {}, "gaps": [], "assumptions": []}
            continue
        details[nid] = {
            "status": a.get("status", "pending"),
            "confidence_floor": a.get("confidence_floor", "?"),
            "payload": a.get("payload", {}),
            "gaps": a.get("gaps", []),
            "assumptions": a.get("assumptions", []),
        }

    # Build upstream/downstream maps from network
    upstream = {}
    downstream = {}
    for edge in self.network["edges"]:
        if edge["type"] == "feedback":
            continue
        downstream.setdefault(edge["from"], []).append(edge["to"])
        upstream.setdefault(edge["to"], []).append(edge["from"])

    node_names_js = json.dumps(NODE_NAMES, ensure_ascii=False)
    details_js = json.dumps(details, ensure_ascii=False)
    upstream_js = json.dumps(upstream, ensure_ascii=False)
    downstream_js = json.dumps(downstream, ensure_ascii=False)

    return f'''<script>
const NODE_NAMES = {node_names_js};
const nodeDetails = {details_js};
const upstreamMap = {upstream_js};
const downstreamMap = {downstream_js};

const drawer = document.getElementById('drawer');
const drawerOverlay = document.getElementById('drawer-overlay');
const drawerNodeId = document.getElementById('drawer-node-id');
const drawerNodeTitle = document.getElementById('drawer-node-title');
const drawerStatus = document.getElementById('drawer-status');
const drawerBody = document.getElementById('drawer-body');

function openDrawer(nodeId) {{
  const d = nodeDetails[nodeId];
  if (!d) return;
  const name = NODE_NAMES[nodeId] || nodeId;
  drawerNodeId.textContent = nodeId.toUpperCase();
  drawerNodeTitle.textContent = name;

  // Status line
  const conf = d.confidence_floor || '—';
  drawerStatus.innerHTML = `<span class="drawer-status-badge">${{d.status}}</span> · 置信度 ${{conf}}`;

  // Build body
  let html = '';

  // Payload table
  html += '<div class="drawer-section"><div class="drawer-section-title">计算结果</div>';
  html += renderPayload(d.payload);
  html += '</div>';

  // Gaps
  if (d.gaps && d.gaps.length) {{
    html += `<div class="drawer-section"><div class="drawer-section-title">缺口 (${{d.gaps.length}})</div>`;
    d.gaps.forEach(g => {{
      const icon = g.severity === 'error' ? '❌' : g.severity === 'warning' ? '⚠️' : 'ℹ️';
      html += `<div class="drawer-gap ${{g.severity}}">${{icon}} <strong>${{g.rule}}</strong> ${{g.msg}}</div>`;
    }});
    html += '</div>';
  }}

  // Assumptions
  if (d.assumptions && d.assumptions.length) {{
    html += `<div class="drawer-section"><div class="drawer-section-title">假设 (${{d.assumptions.length}})</div>`;
    d.assumptions.forEach(a => {{
      html += `<div class="drawer-assumption"><span class="conf-badge">${{a.confidence}}</span> `
            + `<strong>${{a.field}}</strong> = ${{a.value}} ${{a.unit||''}} — ${{a.rationale}}</div>`;
    }});
    html += '</div>';
  }}

  // Upstream / Downstream
  const up = upstreamMap[nodeId] || [];
  const down = downstreamMap[nodeId] || [];
  if (up.length || down.length) {{
    html += '<div class="drawer-section"><div class="drawer-section-title">数据依赖</div>';
    if (up.length) html += `<div class="drawer-dep">▲ 上游: ${{up.map(n => n.toUpperCase() + ' ' + (NODE_NAMES[n]||'')).join(', ')}}</div>`;
    if (down.length) html += `<div class="drawer-dep">▼ 下游: ${{down.map(n => n.toUpperCase() + ' ' + (NODE_NAMES[n]||'')).join(', ')}}</div>`;
    html += '</div>';
  }}

  drawerBody.innerHTML = html;
  drawer.classList.add('open');
  drawerOverlay.classList.add('open');
}}

function renderPayload(payload, depth) {{
  depth = depth || 0;
  if (!payload || typeof payload !== 'object') return '<span>' + String(payload) + '</span>';
  if (Array.isArray(payload)) {{
    if (payload.length === 0) return '<span>[]</span>';
    if (payload.length > 10) return '<span>[' + payload.length + ' items]</span>';
    let h = '<div class="drawer-array">';
    payload.forEach((item, i) => {{
      if (typeof item === 'object' && item !== null) {{
        h += '<div class="drawer-array-item">' + renderPayload(item, depth+1) + '</div>';
      }} else {{
        h += '<div class="drawer-array-item">' + String(item) + '</div>';
      }}
    }});
    return h + '</div>';
  }}
  // Object
  let h = '<table class="drawer-kv-table">';
  for (const [k, v] of Object.entries(payload)) {{
    if (v === null || v === undefined || v === '') continue;
    if (typeof v === 'object' && depth < 2) {{
      h += `<tr><td class="kv-key">${{k}}</td><td>${{renderPayload(v, depth+1)}}</td></tr>`;
    }} else if (typeof v === 'object') {{
      h += `<tr><td class="kv-key">${{k}}</td><td>[object]</td></tr>`;
    }} else {{
      h += `<tr><td class="kv-key">${{k}}</td><td class="kv-val">${{v}}</td></tr>`;
    }}
  }}
  return h + '</table>';
}}

function closeDrawer() {{
  drawer.classList.remove('open');
  drawerOverlay.classList.remove('open');
}}

document.getElementById('drawer-close').addEventListener('click', closeDrawer);
document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);

// Node click handlers
document.querySelectorAll('.node-group').forEach(node => {{
  node.addEventListener('click', () => openDrawer(node.dataset.node));
}});

// Stagger animations
document.querySelectorAll('.animate-in').forEach((el, i) => {{
  el.style.animationDelay = (i * 0.12) + 's';
}});
</script>'''
```

**Step 2: Generate and verify drawer interaction**

Open HTML in browser, click a node — verify drawer slides in from right with payload data, gaps, assumptions, and dependency info.

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): implement side drawer with full node detail view"
```

---

### Task 8: Implement legend and footer

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Implement `_render_legend` and `_render_footer`**

```python
def _render_legend(self) -> str:
    items = [
        ("#3b82f6", "需求分解"),
        ("#06b6d4", "组件分解"),
        ("#8b5cf6", "验证计划"),
        ("#10b981", "成本计算"),
        ("#ec4899", "项目计划"),
        ("#f59e0b", "报价汇总"),
        ("#2a3040", "待完成"),
    ]
    html = '<div class="legend animate-in">'
    for color, label in items:
        html += f'<div class="legend-item"><div class="legend-swatch" style="background:{color}"></div><span>{label}</span></div>'
    html += '</div>'
    return html

def _render_footer(self, proj: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    customer = proj.get("customer", "")
    proj_id = proj.get("id", self.project_path.name)
    return f'''
    <div class="footer animate-in">
      <span>Q^AI · {customer} {proj_id} 成本数据流</span>
      <span>Generated {now}</span>
    </div>'''
```

**Step 2: Generate, verify legend and footer show at bottom**

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "feat(diagram): add legend and footer"
```

---

### Task 9: Visual polish and browser testing

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts/diagram.py`

**Step 1: Generate the diagram from FBFS test data**

Run: `cd /home/chu2026/Documents/APQPOS && python3 -c "import sys; sys.path.insert(0,'.claude/skills/apqp-os/scripts'); from diagram import DataflowDiagram; DataflowDiagram('FBFS').generate()"`

**Step 2: Open in browser and check**

Use webapp-testing or manual browser check:
- [ ] All 18 nodes visible with correct data
- [ ] Edges connect properly (no overlapping lines, correct routing)
- [ ] Completed nodes in phase colors, pending nodes in grey (if any)
- [ ] Animated particles on completed edges
- [ ] Cost bar shows 6 segments with correct percentages
- [ ] Reliability matrix shows S3/S4 assumptions
- [ ] Click any node → drawer opens with payload, gaps, assumptions
- [ ] Click close or overlay → drawer closes
- [ ] Legend and footer present
- [ ] Responsive on smaller screens

**Step 3: Fix any layout/visual issues**

Adjust `NODE_LAYOUT` coordinates, edge routing, font sizes, or spacing as needed. The key constraint: all 18 nodes must be visible without overlap, with clear phase grouping.

**Step 4: Commit**

```bash
git add .claude/skills/apqp-os/scripts/diagram.py
git commit -m "fix(diagram): visual polish — layout, edge routing, responsive"
```

---

### Task 10: Integrate into SKILL.md

**Files:**
- Modify: `/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/SKILL.md`

**Step 1: Add step 7.5 to Node Execution Pattern**

After the current step 7 (Write report), add:

```markdown
7.5. **Update dataflow diagram** — regenerate the interactive HTML visualization:
\```python
from diagram import DataflowDiagram
DataflowDiagram('<project_path>').generate()
\```
This updates `artifacts/dataflow-diagram.html` with the latest node data. The diagram shows all 18 nodes progressively: completed nodes in color with real data, pending nodes in grey.
```

**Step 2: Add to Output Artifacts table**

Add a row:
```
| 节点执行数据 | 交互式数据流图 | `artifacts/dataflow-diagram.html` |
```

**Step 3: Commit**

```bash
git add .claude/skills/apqp-os/SKILL.md
git commit -m "feat(skill): integrate diagram generation as step 7.5 in node execution"
```

---

### Task 11: End-to-end test with FBFS project

**Step 1: Run diagram generation**

```bash
cd /home/chu2026/Documents/APQPOS
python3 -c "
import sys
sys.path.insert(0, '.claude/skills/apqp-os/scripts')
from diagram import DataflowDiagram
d = DataflowDiagram('FBFS')
path = d.generate()
print(f'Generated: {path}')
print(f'Size: {path.stat().st_size / 1024:.1f} KB')
"
```

Expected: File generated, size roughly 30-60 KB (single-file HTML).

**Step 2: Compare with original FBFS diagram**

Open both `FBFS/artifacts/dataflow-diagram.html` (new) and compare with the original (backup if needed). Verify:
- Same visual quality
- More nodes visible (18 vs original 12)
- Drawer interaction works
- Cost bar and reliability matrix present

**Step 3: Final commit**

```bash
git add .
git commit -m "feat: dataflow diagram generator — 18-node progressive HTML visualization

- scripts/diagram.py: DataflowDiagram class generates single-file HTML
- Fixed SVG layout for all 18 DAG nodes with phase coloring
- Progressive rendering: completed nodes in color, pending in grey
- Click-to-open side drawer with full payload, gaps, assumptions
- Cost breakdown bar from n16 with fixed hover interaction
- Reliability risk matrix from S3/S4 assumptions
- Integrated as step 7.5 in SKILL.md node execution pattern"
```
